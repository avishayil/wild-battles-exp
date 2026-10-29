# Credits

- **Wild Battles (PWB1)** base mod — **RicoSantos**. This project extends that mod and
  ships the base records (verbatim) in the unified build. All credit for the wild-battle
  system itself goes to RicoSantos.
- **raulzrrs/letsgo-recomp** — a recompiler for the Eevee 1.0.0 build whose
  `runtime/hle/wildbattle.c` documents the native faint/EXP mechanism (instant-end flag
  clear, model-joint guard, EXP predicate, result rewrite, after-battle evolution). This
  project re-derived the equivalent addresses for **Pikachu 1.0.2** and reproduced the
  mechanisms as a static IPSwitch .pchtxt. recomp's addresses are build-specific and were
  not copied.
- Reverse engineering, address mapping, and the static-patch implementation for Pikachu
  1.0.2: this repository.

This is a fan modding / preservation project; it contains no game code or assets, only
address-based binary patches you apply to your own legally obtained copy.
