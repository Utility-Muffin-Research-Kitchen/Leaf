# RetroArch GLSL shader notices

Leaf's MLP1 shader bundle is assembled directly from the original upstream
repositories at the exact commits recorded in
`platforms/mlp1/shaders/manifest.json`:

- [`libretro/glsl-shaders`](https://github.com/libretro/glsl-shaders):
  selected public-domain and MIT-licensed files with embedded notices.
- [`SkyWalker541/PT-SkyWalker541`](https://github.com/SkyWalker541/PT-SkyWalker541):
  MIT.
- [`Woohyun-Kang/Sharp-Shimmerless-Shader`](https://github.com/Woohyun-Kang/Sharp-Shimmerless-Shader):
  CC0 1.0.

Leaf does not source these files from another firmware. The generated bundle
ships the applicable repository license texts and retains embedded notices.
Its manifest records the original upstream, commit, tree, source path, SHA-256
digest, license classification, and evidence path for every installed file.

Leaf does not enable a shader automatically. The nine thin presets under
`leaf-recommended/` passed visual review and 60-second performance checks at
60/120 Hz, with Black Frame Insertion tested where the core/content path is
compatible. PT SkyWalker541, Sharp Shimmerless, and CRT Hyllian Fast passed the
full game-content gates and back five of those recommendations. CRT Lottes Fast
loads safely but remains advanced-only because it measured 34.017 FPS at 60 Hz.
CRT Lite must be used with BFI off. Qualification details and constraints are
recorded in the bundle manifest and its pinned recommendation metadata.
