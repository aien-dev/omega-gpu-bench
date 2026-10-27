#!/usr/bin/env python3
# kit/ck.py -- run one Omega-encoded cubin on this machine's NVIDIA GPU and check every output word.
#
#   ck.py probe              print the GPU name, compute capability and driver API version
#   ck.py CUBIN KIND         KIND is vecadd or neg; prints one JSON line
#
# The cubin is loaded with NVIDIA's driver library (libcuda, cuModuleLoadData) and launched with
# cuLaunchKernel. This is an interop oracle for Omega's machine-code encoder (asm2 + sm80.tbl) and
# cubin writer (kernels/src/cubin.om). It is NOT CUDA++'s own user-space driver path.
#
# Inputs are public and deterministic: a[i], b[i] = Python random.Random(20261026).getrandbits(32),
# n = 2^20 + 7, 128 threads per block. vecadd must give c[i] = (a[i] + b[i]) mod 2^32 for every i.
# neg is the same kernel with one register operand changed (R4 for R5), so a working check must
# report mismatches for it (NEG_DETECTED). A neg that fails to load or run is LOAD_FAIL/RUN_FAIL,
# never NEG_DETECTED. A correct vecadd is then timed on its own 2^26-element buffers (768 MiB moved per
# launch, so the GPU and not Python's launch overhead sets the pace) with CUDA events: 3 warm-up launches,
# then 5 rounds of 20 back-to-back launches; kernel_ms is the median round / 20, and
# gbps = 12 * 2^26 bytes / kernel time (two 4-byte loads and one 4-byte store per element).
#
# Every driver entry point has explicit argtypes and every return code is checked. Each call is
# announced on stderr ("stage=...") first and faulthandler is on, so a crash names the faulting call.
#
# INTERIM host glue (Python + ctypes), derived from the CloudKernels lane's ck.py (2026-10-26) with
# three changes: neg counts only when it ran, the output buffer hash is recorded, and vecadd is timed.
# Omega successor: an omc-built loader that maps the cubin through CUDA++'s user-space driver path,
# with the CPU reference in .om (see DEPENDENCIES.md).
import ctypes, faulthandler, hashlib, json, os, random, statistics, sys
from array import array

faulthandler.enable()
N, B, SEED, M = (1 << 20) + 7, 128, 20261026, 0xFFFFFFFF
C, P, U32, U64, SZ = ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint64, ctypes.c_size_t
PI, PP = ctypes.POINTER(C), ctypes.POINTER(P)
SIGS = {
    "cuInit": [U32], "cuDeviceGet": [PI, C], "cuDeviceGetAttribute": [PI, C, C],
    "cuDriverGetVersion": [PI], "cuDeviceGetName": [ctypes.c_char_p, C, C],
    "cuCtxCreate_v2": [PP, U32, C], "cuModuleLoadData": [PP, ctypes.c_char_p],
    "cuModuleGetFunction": [PP, P, ctypes.c_char_p], "cuMemAlloc_v2": [ctypes.POINTER(U64), SZ],
    "cuMemcpyHtoD_v2": [U64, P, SZ], "cuMemcpyDtoH_v2": [P, U64, SZ], "cuCtxSynchronize": [],
    "cuLaunchKernel": [P, U32, U32, U32, U32, U32, U32, U32, P, PP, PP],
    "cuEventCreate": [PP, U32], "cuEventRecord": [P, P], "cuEventSynchronize": [P],
    "cuEventElapsedTime": [ctypes.POINTER(ctypes.c_float), P, P],
    "cuGetErrorName": [C, ctypes.POINTER(ctypes.c_char_p)],
}
out = {}


def emit(code):
    print(json.dumps(out, sort_keys=True))
    sys.stdout.flush()
    sys.exit(code)


class Fail(Exception):
    pass


def load_driver():
    fake = os.environ.get("OGB_FAKE_DRIVER")
    if fake:  # test fixture only (tests/fakecuda.py); the validator rejects receipts made with it
        sys.path.insert(0, os.path.dirname(os.path.abspath(fake)))
        out["driver"] = "fake"
        return __import__(os.path.splitext(os.path.basename(fake))[0]).Driver()
    out["driver"] = "libcuda"
    lib = ctypes.CDLL("libcuda.so.1")
    for fname, at in SIGS.items():
        f = getattr(lib, fname)
        f.argtypes, f.restype = at, C
    return lib


def call(what, *a):
    sys.stderr.write("stage=%s\n" % what)
    sys.stderr.flush()
    r = getattr(cu, what)(*a)
    if r != 0:
        s = ctypes.c_char_p()
        cu.cuGetErrorName(r, ctypes.byref(s))
        out["error"] = "%s: %d %s" % (what, r, s.value.decode() if s.value else "")
        raise Fail(what)


try:
    cu = load_driver()
except OSError as e:
    out.update(verdict="NO_DRIVER", error=str(e))
    emit(2)

try:
    call("cuInit", 0)
    dev = C()
    call("cuDeviceGet", ctypes.byref(dev), 0)
    mj, mn, dv = C(), C(), C()
    call("cuDeviceGetAttribute", ctypes.byref(mj), 75, dev.value)  # COMPUTE_CAPABILITY_MAJOR
    call("cuDeviceGetAttribute", ctypes.byref(mn), 76, dev.value)  # COMPUTE_CAPABILITY_MINOR
    call("cuDriverGetVersion", ctypes.byref(dv))
    nm = ctypes.create_string_buffer(256)
    call("cuDeviceGetName", nm, 256, dev.value)
    out.update(device=nm.value.decode(errors="replace"), cc="%d.%d" % (mj.value, mn.value),
               cuda_driver_api=dv.value)
except Fail:
    out["verdict"] = "INIT_FAIL"
    emit(2)
if sys.argv[1] == "probe":
    out["verdict"] = "PROBED"
    emit(0)

path, kind = sys.argv[1], sys.argv[2]
img = open(path, "rb").read()
out.update(cubin=os.path.basename(path), kind=kind, cubin_sha256=hashlib.sha256(img).hexdigest())
try:
    ctx, mod, fn = P(), P(), P()
    call("cuCtxCreate_v2", ctypes.byref(ctx), 0, dev.value)
    call("cuModuleLoadData", ctypes.byref(mod), img)
    call("cuModuleGetFunction", ctypes.byref(fn), mod, kind.encode())
except Fail:
    out["verdict"] = "LOAD_FAIL"
    emit(1)

rng = random.Random(SEED)
a = array("I", (rng.getrandbits(32) for _ in range(N)))
b = array("I", (rng.getrandbits(32) for _ in range(N)))
ref = array("I", ((x + y) & M for x, y in zip(a, b)))
U = ctypes.c_uint32 * N
h = U()


def buffers(count, sources):
    bufs = []
    for src in sources:
        p = U64()
        call("cuMemAlloc_v2", ctypes.byref(p), 4 * count)
        if src is not None:
            host = U.from_buffer_copy(src.tobytes())
            call("cuMemcpyHtoD_v2", p.value, ctypes.cast(host, P), 4 * count)
        bufs.append(p)
    n = U32(count)
    keep = (bufs[0], bufs[1], bufs[2], n)
    return keep, (P * 4)(*[ctypes.cast(ctypes.byref(x), P) for x in keep])


def launch(count, args):
    call("cuLaunchKernel", fn, (count + B - 1) // B, 1, 1, B, 1, 1, 0, None, ctypes.cast(args, PP), None)


try:
    keep, args = buffers(N, (a, b, array("I", bytes(4 * N))))
    launch(N, args)
    call("cuCtxSynchronize")
    call("cuMemcpyDtoH_v2", ctypes.cast(h, P), keep[2].value, 4 * N)
except Fail:
    out["verdict"] = "RUN_FAIL"
    emit(1)

g = array("I", bytes(h))
bad = [i for i in range(N) if g[i] != ref[i]]
le = g if sys.byteorder == "little" else array("I", g)
if sys.byteorder != "little":
    le.byteswap()
out.update(output_sha256=hashlib.sha256(le.tobytes()).hexdigest(), checked=N, mismatches=len(bad),
           first_bad=[[i, g[i], ref[i]] for i in bad[:3]])
if kind == "neg":
    out["verdict"] = "NEG_DETECTED" if bad else "NEG_MISSED"
    emit(0 if bad else 1)
out["verdict"] = "WRONG" if bad else "PASS"
if bad:
    emit(1)

NT = 1 << 26
try:
    tkeep, targs = buffers(NT, (None, None, None))  # contents do not matter for timing
    e0, e1, ms = P(), P(), ctypes.c_float()
    call("cuEventCreate", ctypes.byref(e0), 0)
    call("cuEventCreate", ctypes.byref(e1), 0)
    for _ in range(3):
        launch(NT, targs)
    call("cuCtxSynchronize")
    rounds = []
    for _ in range(5):
        call("cuEventRecord", e0, None)
        for _ in range(20):
            launch(NT, targs)
        call("cuEventRecord", e1, None)
        call("cuEventSynchronize", e1)
        call("cuEventElapsedTime", ctypes.byref(ms), e0, e1)
        rounds.append(ms.value / 20)
    kms = statistics.median(rounds)
    out.update(timing_n=NT, kernel_ms=round(kms, 6), gbps=round(12 * NT / (kms * 1e6), 3))
except Fail:
    out["timing_error"] = out.pop("error")
emit(0)
