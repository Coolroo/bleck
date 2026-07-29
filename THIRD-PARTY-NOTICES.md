# Third-party notices

`bleck` is MIT licensed ([`LICENSE`](LICENSE)). This file lists third-party
material that ships inside it, and the notices that material requires.

## SeekyCt/spm-headers

<https://github.com/SeekyCt/spm-headers>

Derived from the MIT-licensed `include/` and `linker/` directories:

| What | Where |
|---|---|
| evt builtin names and argument counts | `bleck/script/catalog.json` |
| Struct layouts and field offsets quoted in docstrings | `bleck/formats/setup.py`, `bleck/script/emit/*` |

```
MIT License

Copyright (c) 2022 Seeky

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Adding to this file

Anything derived from another project that lands under `bleck/` needs a row
above and its licence notice below it. `spm-headers` splits its licensing —
`include/`, `decomp/` and `linker/` are MIT, `mod/` is GPLv3 — so check which
directory a file came from before deriving from it.
