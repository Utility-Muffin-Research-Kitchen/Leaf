# RetroArch GLSL shader notices

Leaf's MLP1 shader bundle is built from the
[`libretro/glsl-shaders`](https://github.com/libretro/glsl-shaders) repository
at the exact commit recorded in
`platforms/mlp1/shaders/manifest.json`.

The initial bundle contains only presets whose complete dependency closures
carry an embedded public-domain notice. Those notices remain present inside the
copied shader source files. The bundle manifest records the source path,
SHA-256 digest, license classification, and evidence path for every installed
file.

Leaf does not enable a shader automatically. Every preset in the initial bundle
is marked at least `loads` after MLP1 compile, render, lifecycle, and relaunch
checks. The four thin presets under `leaf-recommended/` also passed visual
review and 60-second performance checks at 60/120 Hz, with Black Frame
Insertion tested where the core/content path is compatible. Qualification
details and constraints are recorded in the bundle manifest and its pinned
recommendation metadata.
