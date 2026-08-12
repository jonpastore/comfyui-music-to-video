"""Cast ACE-Step's bf16 tensors to fp16 so it runs on Turing (no bf16 kernels).

Only the RANGE is at risk: bf16 carries an 8-bit exponent like fp32, fp16 only
5 bits, so anything above 65504 saturates to inf. Precision actually IMPROVES
(fp16 has 10 mantissa bits to bf16's 7). So the whole safety question is one
number per tensor, and this refuses to write if any tensor is near the ceiling.
"""
import sys, torch
from safetensors import safe_open
from safetensors.torch import save_file

SRC, DST = sys.argv[1], sys.argv[2]
FP16_MAX = 65504.0
HEADROOM = 0.5          # refuse if any value exceeds half the ceiling

meta, out, worst, n_bf16, bad = {}, {}, [], 0, []
with safe_open(SRC, framework="pt", device="cpu") as f:
    meta = f.metadata() or {}
    for k in f.keys():
        t = f.get_tensor(k)
        if t.dtype == torch.bfloat16:
            n_bf16 += 1
            m = t.abs().max().item() if t.numel() else 0.0
            worst.append((m, k))
            if m > FP16_MAX * HEADROOM:
                bad.append((m, k))
            out[k] = t.to(torch.float16)
        else:
            out[k] = t

worst.sort(reverse=True)
print(f"bf16 tensors: {n_bf16}")
print("largest absolute values:")
for m, k in worst[:5]:
    print(f"  {m:12.4f}  {k}")
print(f"fp16 ceiling: {FP16_MAX}  (refusing above {FP16_MAX*HEADROOM})")

if bad:
    print(f"REFUSING: {len(bad)} tensor(s) too close to the fp16 ceiling")
    sys.exit(1)

save_file(out, DST, metadata=meta)
# prove the written file has no inf/nan
with safe_open(DST, framework="pt", device="cpu") as f:
    bad2 = [k for k in f.keys()
            if not torch.isfinite(f.get_tensor(k).float()).all()]
print("non-finite tensors after cast:", len(bad2))
sys.exit(1 if bad2 else 0)
