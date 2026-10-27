# tests/fakecuda.py -- TEST FIXTURE, not a GPU. A pure-Python stand-in for the dozen libcuda entry points
# kit/ck.py calls, so CI (which has no GPU) can drive ./run end to end: probe, load, launch, copy back,
# event timing, receipt writing. ck.py loads it only when OGB_FAKE_DRIVER points at this file and then
# stamps "driver": "fake" into every result; tools/validate.py rejects such receipts unless it is given
# --allow-fake (used only by tests/run.sh). The kernel is emulated on the CPU, so nothing here says
# anything about a real GPU.
#
# OGB_FAKE_CC    compute capability to report (default 8.9)
# OGB_FAKE_MODE  "" (vecadd correct), "wrong" (vecadd corrupts three words), "nogpu" (cuInit fails 100)
import ctypes, os
from array import array

ELF = b"\x7fELF"


class Driver:
    def __init__(self):
        self.mem, self.next, self.img, self.kernel = {}, 0x10000, None, None
        self.mode = os.environ.get("OGB_FAKE_MODE", "")
        self.cc = [int(x) for x in os.environ.get("OGB_FAKE_CC", "8.9").split(".")]

    @staticmethod
    def _set(ref, value):
        ref._obj.value = value
        return 0

    def cuInit(self, flags):
        return 100 if self.mode == "nogpu" else 0  # CUDA_ERROR_NO_DEVICE

    def cuDeviceGet(self, ref, ordinal):
        return self._set(ref, 0)

    def cuDeviceGetAttribute(self, ref, attr, dev):
        return self._set(ref, self.cc[0] if attr == 75 else self.cc[1])

    def cuDriverGetVersion(self, ref):
        return self._set(ref, 13000)

    def cuDeviceGetName(self, buf, size, dev):
        buf.value = b"FAKE DRIVER (test fixture, not a GPU)"
        return 0

    def cuCtxCreate_v2(self, ref, flags, dev):
        return self._set(ref, 1)

    def cuModuleLoadData(self, ref, img):
        if not img.startswith(ELF):
            return 200  # CUDA_ERROR_INVALID_IMAGE
        self.img = img
        return self._set(ref, 1)

    def cuModuleGetFunction(self, ref, mod, name):
        if b"\0" + name + b"\0" not in self.img:
            return 500  # CUDA_ERROR_NOT_FOUND
        self.kernel = name.decode()
        return self._set(ref, 1)

    def cuMemAlloc_v2(self, ref, size):
        handle, self.next = self.next, self.next + ((size + 0xFFFF) & ~0xFFFF)
        self.mem[handle] = bytearray(size) if size <= (16 << 20) else None  # timing buffers stay virtual
        return self._set(ref, handle)

    def cuMemcpyHtoD_v2(self, dptr, host, size):
        self.mem[dptr][:size] = ctypes.string_at(host.value, size)
        return 0

    def cuMemcpyDtoH_v2(self, host, dptr, size):
        ctypes.memmove(host.value, bytes(self.mem[dptr][:size]), size)
        return 0

    def cuLaunchKernel(self, fn, gx, gy, gz, bx, by, bz, shared, stream, args, extra):
        pa, p1, p2 = (ctypes.c_uint64.from_address(args[k]).value for k in range(3))
        n = ctypes.c_uint32.from_address(args[3]).value
        if self.mem[p2] is None:
            return 0
        a, b = array("I", bytes(self.mem[pa][:4 * n])), array("I", bytes(self.mem[p1][:4 * n]))
        if self.kernel == "neg":
            c = array("I", ((x + 1) & 0xFFFFFFFF for x in a))
        else:
            c = array("I", ((x + y) & 0xFFFFFFFF for x, y in zip(a, b)))
            if self.mode == "wrong":
                for i in (5, 77, n - 1):
                    c[i] ^= 1
        self.mem[p2][:4 * n] = c.tobytes()
        return 0

    def cuCtxSynchronize(self):
        return 0

    def cuEventCreate(self, ref, flags):
        return self._set(ref, 1)

    def cuEventRecord(self, ev, stream):
        return 0

    def cuEventSynchronize(self, ev):
        return 0

    def cuEventElapsedTime(self, ref, e0, e1):
        return self._set(ref, 20.0)

    def cuGetErrorName(self, r, ref):
        return self._set(ref, b"FAKE_ERROR_%d" % r)
