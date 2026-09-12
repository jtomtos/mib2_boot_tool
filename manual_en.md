# USER MANUAL AND TECHNICAL SPECIFICATION

## MIB2STD Boot Animation Assembly and Decompilation Utility (Boot Tool)

### 1\. GENERAL DESCRIPTION

This script is a specialized engineering tool designed for decompiling (unpacking) and compiling (packing) `.boot` binary animation containers (e.g., `startup.boot`). These containers are utilized in the **MIB2 Std** infotainment head units (Discover Media, Composition Media manufactured by TechniSat/Preh) across Volkswagen Group (VAG) vehicles including VW, Skoda, and Seat.

The utility fully supports processing the proprietary two-channel **MIB2 GRAYA** graphic format, which uses a custom chroma subsampling delta algorithm. It translates binary display opcodes into a human-readable high-level script file (`script.txt`) during extraction and compiles it back into highly optimized binary data during packaging.

\---

### 2\. OPERATING MODES AND CLI PARAMETERS

The script runs exclusively via a Command Line Interface (CLI) and supports two mutually exclusive modes: `unpack` and `pack`.

#### A. Unpack Mode (unpack)

Decompiles a compiled `.boot` container into raw source frames (`.png`) and a text-based animation layout file (`script.txt`).

**CLI Syntax:**

```bash
python mib2\_boot\_tool.py unpack <path\_to\_file.boot> \[<path\_to\_output\_directory>]
```

**Parameters:**

* `file` *(mandatory positional)*: The absolute or relative path to the compiled binary `.boot` file (e.g., `startup.boot`).
* `outdir` *(optional positional)*: The target directory path where all extracted frames and scripts will be written. If omitted, the utility creates a new folder named after the source file (excluding extension) in the current working directory.

#### B. Pack Mode (pack)

Assembles a valid binary `.boot` file from raw directory assets (PNG frames and the `script.txt` text layout), rendering it ready to be flashed or installed onto a head unit.

**CLI Syntax:**

```bash
python mib2\_boot\_tool.py pack <path\_to\_assets\_folder> <output\_file\_name.boot> \[--bits <value>]
```

**Parameters:**

* `folder` *(mandatory positional)*: The source directory containing the execution file `script.txt` and all required `.png` graphical frames referenced within it.
* `output` *(mandatory positional)*: The target file name or path for the generated binary container (e.g., `custom\_startup.boot`).
* `--bits` *(optional named)*: Accepted range is `1` to `8`. Enforces color depth reduction (posterization) on each channel before conversion. This parameter is highly critical for aggressive compression of long/heavy animations to guarantee the final file fits within the bootloader's strict RAM allocation limits (values like `--bits 4` are recommended if the final binary exceeds 1 MB).

\---

### 3\. APPENDIX A: ANIMATION LAYOUT SCRIPT SPECIFICATION (script.txt)

The layout text file defines the step-by-step rendering logic processed by the infotainment system's graphics coprocessor. Each functional statement must occupy its own separate line. The `#` symbol declares inline comments (any text following `#` is ignored by the compiler).

During compilation, every valid statement converts into a uniform 32-byte binary block consisting of a command ID and up to 6 parameters. During extraction, an automated tracking comment `# ID=<number>` appended to the end of each line denotes its original command index within the binary stack. These metadata IDs can be excluded when creating a script manually.

#### MIB2 Graphic Engine Command Reference Table

|Command Name|Description|Practical Example|
|-|-|-|
|`begin()`|Initializes and spawns the execution scene context. Must always be the first command.|`begin()`|
|`end()`|Finalizes the animation layout sequence and hands control over to the OS bootloader.|`end()`|
|`clear\_screen()`|Instantly flushes the active frame buffer (paints the entire screen pure black).|`clear\_screen()`|
|`set\_resolution(W, H)`|Declares the global display layout boundaries. Standard resolution is 800x480.|`set\_resolution(800, 480)`|
|`draw\_bg(img\_name, x, y)`|Draws a base, full-screen background graphic.|`draw\_bg(img\_00, x=0, y=0)`|
|`draw\_sticker(...)`|Blits an individual sprite/frame layer specifying transparency and Z-order height.|`draw\_sticker(img\_01, x=240, y=100, blend\_mode=19, z\_index=1, frame\_buffer=0)`|
|`wait(seconds)`|Halts script execution for a specified interval (increments of 0.01 seconds).|`wait(0.15)`|
|`start\_animation()`|Triggers looped hardware-accelerated playback of the buffered image stack.|`start\_animation()`|
|`if STICKER == ID:`|Conditional execution statement used to fork layouts based on system profiles.|`if STICKER == 0:`|
|`else:`|Alternate statement path taken if the primary `if` condition evaluates to false.|`else:`|
|`endif`|Mandatory termination statement closing any open conditional `if/else` block.|`endif`|
|`set animation id=ID`|Service directive setting the boot animation ID mapping for specific UI skins.|`set animation id=101`|

\---

### 4\. DETAILED COMMAND ATTRIBUTE BREAKDOWN

#### set\_resolution(width, height)

* **width**: Target display frame width in pixels. For standard MIB2 Std screens, this defaults to `800`.
* **height**: Target display frame height in pixels. This defaults to `480`.

#### draw\_bg(image\_name, x, y)

* **image\_name**: Reference name of the image asset file without its extension (e.g., `img\_00`). The compiler scans for `img\_00.png` within the asset path. Names must be alphanumeric.
* **x**: Coordinates offset on the X-axis (horizontal) matching the top-left boundary of the background. Defaults to `0`.
* **y**: Coordinates offset on the Y-axis (vertical) matching the top-left boundary of the background. Defaults to `0`.

#### draw\_sticker(image\_name, x, y, blend\_mode, z\_index, frame\_buffer)

* **image\_name**: Reference name of the sprite/frame asset to render (e.g., `img\_01`).
* **x** / **y**: Exact pixel alignment targeting the top-left coordinate anchor of the sprite. Allows positioning low-resolution logo frames dead center onto the background (e.g., `x=250, y=140`).
* **blend\_mode**: Alpha channel transparency blending type selector.

  * `1`: Renders the frame completely opaque, discarding embedded transparency.
  * `19`: Activates **Premultiplied Alpha** rendering (standard profile). Informs the GPU coprocessor that the PNG pixel colors are pre-multiplied by their alpha transparency value. This eliminates fringe edge artifacts (black/white glowing halos) and accelerates rendering speed.
* **z\_index**: Stack priority layers hierarchy (Z-order). Frames assigned `z\_index=1` slice over standard backgrounds (`draw\_bg` initializes at `0` or lower).
* **frame\_buffer**: Hardware frame buffer selection slot mapping. The default value is `0` (or `4294967295` for automated resource provisioning).

#### wait(time\_period)

* **time\_period**: Suspension time interval written as a float value (e.g., `0.04`, `0.1`, `1.50`). The internal scheduler evaluates cycles with centisecond precision (the engine applies a `\* 100` multiplier to gauge system ticks). This allows precise frames-per-second (FPS) pacing adjustments.

#### if STICKER == condition\_id:

* **condition\_id**: Integer tag binding execution to a specific configuration profile. In the factory scripts, the **STICKER == 0** condition is checked (base model). Other **condition_id** options weren't verified.

