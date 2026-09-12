#!/usr/bin/env python3
import os
import sys
import struct
import re
import argparse
import subprocess

def install_and_import(package):
    """Checks if a package is installed and prompts the user to install it if missing."""
    try:
        __import__(package)
    except ImportError:
        print(f"Library '{package}' not found.")
        user_input = (
            input(f"Do you want to install '{package}' right now? (y/n): ")
            .strip()
            .lower()
        )
        if user_input in ["y", "yes"]:
            print(f"Installing library '{package}'...")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", package])
                __import__(package)
                print(f"Library '{package}' successfully installed and imported.")
            except subprocess.CalledProcessError:
                print(f"Error: Failed to install library '{package}'.")
                sys.exit(1)
        else:
            print(f"Installation canceled. The script cannot continue without '{package}'.")
            sys.exit(1)

# Automatically check and install dependencies
install_and_import("zlib")
install_and_import("numpy")
install_and_import("PIL")

import zlib
import numpy as np
from PIL import Image, ImageOps

# ==============================================================================
#                          PACK MODE (PACK)
# ==============================================================================

def encode_rgb_to_mib2(img_path, is_premultiplied=False, color_bits=None):
    """Encodes a standard PNG into a binary MIB2 array (GRAYA) with color optimization."""
    with Image.open(img_path) as img:
        width, height = img.size

        # Geometry validation
        if width % 2 != 0:
            raise ValueError(
                f"Critical error in file {os.path.basename(img_path)}: "
                f"Width ({width}px) MUST be even! This will break the chroma subsampling algorithm."
            )
        
        if is_premultiplied:
            if img.mode != "RGBA":
                print(f"[!] Warning for {os.path.basename(img_path)}: For blend_mode=19 (Premultiplied), an RGBA image is recommended.")
            img = img.convert("RGBA")
        else:
            img = img.convert("RGB")

        # Size optimization: color depth reduction
        if color_bits is not None and color_bits < 8:
            if img.mode == "RGBA":
                r, g, b, a = img.split()
                rgb_img = Image.merge("RGB", (r, g, b))
                rgb_img = ImageOps.posterize(rgb_img, bits=color_bits)
                r, g, b = rgb_img.split()
                img = Image.merge("RGBA", (r, g, b, a))
            else:
                img = ImageOps.posterize(img, bits=color_bits)
                
        rgb_array = np.array(img, dtype=np.int32)

    if is_premultiplied:
        r_src, g_src, b_src, a_src = rgb_array[:,:,0], rgb_array[:,:,1], rgb_array[:,:,2], rgb_array[:,:,3]
        alpha_normalized = a_src.astype(np.float32) / 255.0
        r = (r_src * alpha_normalized).astype(np.int32)
        g = (g_src * alpha_normalized).astype(np.int32)
        b = (b_src * alpha_normalized).astype(np.int32)
        alpha_out = a_src.astype(np.uint8)
    else:
        r, g, b = rgb_array[:,:,0], rgb_array[:,:,1], rgb_array[:,:,2]
        alpha_out = None

    co = r - g
    cg = b - g
    px = np.zeros_like(g, dtype=np.uint8)
    px[:, 0::2] = np.clip(cg[:, 0::2] + 128, 0, 255)
    px[:, 1::2] = np.clip(co[:, 1::2] + 128, 0, 255)
    g_out = np.clip(g, 0, 255).astype(np.uint8)

    if is_premultiplied:
        px = alpha_out

    dest_main = np.stack([px, g_out], axis=-1)
    return width, height, dest_main.tobytes()

def parse_high_level_script(script_path):
    """Parses a high-level text animation script into binary opcodes."""
    compiled_blocks = []
    premultiplied_images = set()
    
    patterns = {
        'begin': re.compile(r'(?i)begin\(\)'),
        'end': re.compile(r'(?i)end\(\)'),
        'clear': re.compile(r'(?i)clear_screen\(\s*\)'),
        'resolution': re.compile(r'(?i)set_resolution\(\s*(\d*)\s*,\s*(\d*)\s*\)'),
        'draw_bg': re.compile(r'(?i)draw_bg\(\s*([a-zA-Z0-9_\-]+)\s*,\s*x\s*=\s*(-?\d*)\s*,\s*y\s*=\s*(-?\d*)\s*\)'),
        'draw_sticker': re.compile(
            r'(?i)draw_sticker\s*\(\s*([a-zA-Z0-9_\-]+)\s*,\s*'
            r'x\s*=\s*(-?\d*)\s*,\s*'
            r'y\s*=\s*(-?\d*)\s*,\s*'
            r'blend_mode\s*=\s*(\d*)\s*,\s*'
            r'z_index\s*=\s*(-?\d*)\s*,\s*'
            r'frame_buffer\s*=\s*(-?\d*)\s*\)'
        ),
        'wait': re.compile(r'(?i)wait\s*\(\s*(\d+\.?\d*)\s*\)'),
        'start_anim': re.compile(r'(?i)start_animation\(\s*\)'),
        'if_stmt': re.compile(r'(?i)if\s+STICKER\s+==\s+(\d+)\s*:'),
        'else_stmt': re.compile(r'(?i)else:'),
        'endif_stmt': re.compile(r'(?i)endif'),
        'set_id': re.compile(r'(?i)set\s+animation\s+id\s*=\s*(\d+)'),
    }

    to_sys_int = lambda s: int(s) if (s and s.strip()) else 4294967295

    image_name_map = {}
    image_list_ordered = []
    boot_id = 1

    def get_image_id(name):
        if name not in image_name_map:
            image_name_map[name] = len(image_list_ordered)
            image_list_ordered.append(name)
        return image_name_map[name]

    with open(script_path, 'r', encoding='utf-8') as f:
        for idx, line in enumerate(f, 1):
            clean_line = line.split('#')[0].strip()
            if not clean_line: continue

            id_match = re.search(r'(?i)ID\s*=\s*(\d+)', line)
            nn = int(id_match.group(1)) if id_match else idx * 10

            matched = False
            cmd = arg1 = arg2 = arg3 = arg4 = arg5 = arg6 = 4294967295

            for key, expr in patterns.items():
                skip = False
                m = expr.match(clean_line)
                if m:
                    matched = True
                    if key == 'set_id': 
                        boot_id = int(m.group(1))
                        skip = True
                    elif key == 'begin': cmd = 0
                    elif key == 'end': cmd = 1
                    elif key == 'clear': cmd = 2
                    elif key == 'resolution':
                        cmd = 3
                        arg3, arg4 = to_sys_int(m.group(1)), to_sys_int(m.group(2))
                    elif key == 'draw_bg':
                        cmd = 4
                        arg1 = get_image_id(m.group(1))
                        arg3, arg4 = to_sys_int(m.group(2)), to_sys_int(m.group(3))
                    elif key == 'draw_sticker':
                        cmd = 5
                        arg1 = get_image_id(m.group(1))
                        arg3 = to_sys_int(m.group(2))
                        arg4 = to_sys_int(m.group(3))
                        arg2 = to_sys_int(m.group(4))
                        arg5 = to_sys_int(m.group(5))
                        arg6 = to_sys_int(m.group(6))
                        if arg2 == 19:
                            premultiplied_images.add(arg1)
                    elif key == 'wait':
                        cmd = 6
                        arg1 = int(float(m.group(1)) * 100)
                    elif key == 'start_anim': cmd = 7
                    elif key == 'if_stmt':
                        cmd = 10
                        arg2 = int(m.group(1))
                    elif key == 'else_stmt': cmd = 11
                    elif key == 'endif_stmt': cmd = 12
                    break
            if not matched:
                raise SyntaxError(f"Script syntax error at line {idx}: '{clean_line}'")            
            if not skip:
                compiled_blocks.append((nn, cmd, arg1, arg2, arg3, arg4, arg5, arg6))

    return compiled_blocks, premultiplied_images, image_list_ordered, boot_id

def pack_boot(folder_path, output_boot_name, color_bits=None):
    """Main function to assemble a .boot container from a source folder."""
    print(f"[*] Building animation: {folder_path} -> {output_boot_name}")
    if color_bits:
        print(f"[+] Limiting color depth to {color_bits} bits per channel.")

    script_path = os.path.join(folder_path, 'script.txt')
    if not os.path.exists(script_path):
        print(f"[Critical Error] Script file not found: {script_path}")
        return

    try:
        commands, premultiplied_images, image_list_ordered, boot_id = parse_high_level_script(script_path)
    except Exception as e:
        print(f"[Critical Script Parsing Error]: {e}")
        return

    cmd_data = bytearray()
    for block in commands:
        cmd_data.extend(struct.pack('<IIIIIIII', *block))
    cmd_block_len = len(cmd_data)

    images_bin_data = bytearray()
    image_offsets = []
    
    for img_idx, img_name in enumerate(image_list_ordered):
        img_path = os.path.join(folder_path, f"{img_name}.png")
        if not os.path.exists(img_path) and not img_name.endswith('.png'):
            img_path = os.path.join(folder_path, f"{img_name}.png")
        
        if not os.path.exists(img_path):
            print(f"[Critical Error]: Missing asset file '{img_name}.png' declared in the script!")
            sys.exit(1)
            
        is_prem = img_idx in premultiplied_images
        
        try:
            width, height, mib2_bytes = encode_rgb_to_mib2(img_path, is_premultiplied=is_prem, color_bits=color_bits)
        except Exception as e:
            print(e)
            sys.exit(1)
            
        compressed = zlib.compress(mib2_bytes, level=9)
        current_img_offset = len(images_bin_data)
        image_offsets.append(current_img_offset)
        
        images_bin_data.extend(struct.pack('<II', width, height))
        images_bin_data.extend(compressed)

    num_files = len(image_list_ordered)
    if num_files == 0:
        print("[Error] No images declared in the script.")
        return

    header_size = 20
    struct_toc_header_size = 12
    base_images_offset = header_size + cmd_block_len + struct_toc_header_size + num_files * 4   
 
    toc_table = bytearray()
    for offset in image_offsets:
        global_offset = base_images_offset + offset
        toc_table.extend(struct.pack('<I', global_offset))

    final_boot = bytearray()
    final_boot.extend(struct.pack('4s', b'SCRT'))
    final_boot.extend(struct.pack('<IIII', 101, 1, cmd_block_len, boot_id))
    final_boot.extend(cmd_data)
    final_boot.extend(struct.pack('4s', b'MIFA')) 
    final_boot.extend(struct.pack('<II', len(images_bin_data) + num_files * 4, num_files))
    final_boot.extend(toc_table)
    final_boot.extend(images_bin_data)

    final_size_bytes = len(final_boot)
    size_mb = final_size_bytes / (1024 * 1024)

    print("-" * 60)
    print(f"[Info] Total file size: {size_mb:.2f} MB ({final_size_bytes} bytes)")

    if final_size_bytes > 2 * 1024 * 1024:
        print(f"[CRITICAL ERROR]: File size ({size_mb:.2f} MB) exceeds absolute RAM limit of 2 MB! Build aborted.")
        sys.exit(1)
    elif final_size_bytes > 1 * 1024 * 1024:
        print(f"[WARNING]: File size ({size_mb:.2f} MB) exceeds 1 MB limit. It is recommended to use the --bits 4 switch.")
    else:
        print("[+] Success: File fits perfectly within the safe green limit under 1 MB.")
    print("-" * 60)

    with open(output_boot_name, 'wb') as f_out:
        f_out.write(final_boot)
    print(f"[+] Build completed successfully! File written to: {output_boot_name}")


# ==============================================================================
#                          UNPACK MODE (UNPACK)
# ==============================================================================

def load_mib2_to_rgb(width, height, decompressed_bytes, is_premultiplied=False):
    """Decodes raw MIB2 bytes (GRAYA) back into a standard PNG image."""
    # Convert to int32 immediately to prevent uint8 underflow/overflow during math operations
    raw_data = np.frombuffer(decompressed_bytes, dtype=np.uint8).reshape((height, width, 2))
    data = raw_data.astype(np.int32)
    
    px = data[:, :, 0]
    g = data[:, :, 1]
    
    # Secure subtraction, values will correctly go into signed negative range
    chroma_delta = px - 128

    cg_raw = np.zeros_like(chroma_delta, dtype=np.float32)
    co_raw = np.zeros_like(chroma_delta, dtype=np.float32)
    cg_raw[:, 0::2] = chroma_delta[:, 0::2]
    co_raw[:, 1::2] = chroma_delta[:, 1::2]

    # Bilinear chroma component interpolation
    cg_raw[:, 1:-1:2] = (cg_raw[:, 0:-2:2] + cg_raw[:, 2::2]) / 2.0
    cg_raw[:, -1] = cg_raw[:, -2]
    co_raw[:, 2:-1:2] = (co_raw[:, 1:-2:2] + co_raw[:, 3::2]) / 2.0
    co_raw[:, 0] = co_raw[:, 1]
    if width % 2 == 0:
        co_raw[:, -2] = co_raw[:, -1]

    r = (g + co_raw).astype(np.float32)
    b = (g + cg_raw).astype(np.float32)
    g_final = g.astype(np.float32)

    if is_premultiplied:
        alpha_mask = px.astype(np.float32) / 255.0
        alpha_mask = np.where(alpha_mask == 0, 1.0, alpha_mask)
        r /= alpha_mask
        g_final /= alpha_mask
        b /= alpha_mask
        rgb_data = np.stack([r, g_final, b, px], axis=-1)
        mode = "RGBA"
    else:
        rgb_data = np.stack([r, g_final, b], axis=-1)
        mode = "RGB"

    rgb_data = np.clip(rgb_data, 0, 255).astype(np.uint8)
    return Image.fromarray(rgb_data, mode)

def unpack_boot(filename, out_dir):
    """Decompiles a binary .boot file, extracting the script and PNG assets."""
    print(f"[*] Unpacking {filename} -> {out_dir}")
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)

    with open(filename, 'rb') as f_in:
        data = f_in.read()

    (cmd_block_len,) = struct.unpack_from('<I', data, 12)
    num_blocks = cmd_block_len // 32
    (boot_id,) = struct.unpack_from('<I', data, 16)

    cmd_offset = 20
    commands = []
    premultiplied_images = set()

    for _ in range(num_blocks):
        block = struct.unpack_from('<IIIIIIII', data, cmd_offset)
        commands.append(block)
        nn, cmd, arg1, arg2, arg3, arg4, arg5, arg6 = block
        if cmd == 5 and arg2 == 19:
            premultiplied_images.add(arg1)
        cmd_offset += 32

    script_path = os.path.join(out_dir, 'script.txt')
    indent = 0
    with open(script_path, 'w', encoding='utf-8') as f:
        f.write("# MIB2 Boot Animation Script\n")
        f.write(f"set animation id={str(boot_id)}\n")
        for block in commands:
            nn, cmd, arg1, arg2, arg3, arg4, arg5, arg6 = block
            
            if cmd in (1, 11, 12):  # 1: end, 11: else, 12: endif
                indent = max(0, indent - 4)
            
            space = " " * indent
            
            if cmd in (0, 10, 11):  # 0: begin, 10: if, 11: else
                indent += 4

            fmt_z = lambda x: "" if x == 4294967295 else str(x)

            match cmd:
                case 0: line_str = f"begin()"
                case 1: line_str = f"end()"
                case 2: line_str = f"clear_screen()"
                case 3: line_str = f"set_resolution({fmt_z(arg3)}, {fmt_z(arg4)})"
                case 4: line_str = f"draw_bg(img_{str(arg1).zfill(2)}, x={fmt_z(arg3)}, y={fmt_z(arg4)})"
                case 5: line_str = f"draw_sticker(img_{str(arg1).zfill(2)}, x={fmt_z(arg3)}, y={fmt_z(arg4)}, blend_mode={fmt_z(arg2)}, z_index={fmt_z(arg5)}, frame_buffer={fmt_z(arg6)})"
                case 6: line_str = f"wait({arg1*0.01:.2f})"
                case 7: line_str = f"start_animation()"
                case 10: line_str = f"if STICKER == {fmt_z(arg2)}:"
                case 11: line_str = f"else:"
                case 12: line_str = f"endif"
                case _: line_str = f"unknown_command_{cmd}(args={fmt_z(arg1)},{fmt_z(arg2)},{fmt_z(arg3)},{fmt_z(arg4)},{fmt_z(arg5)},{fmt_z(arg6)})"
            
            f.write(f"{space}{line_str} # ID={nn}\n")

    print(f"[+] Animation script saved: {script_path}")

    img_offset = cmd_block_len + 24
    (data_block_size, num_files) = struct.unpack_from('<II', data, img_offset)
    img_offset += 8
    
    offset_array = [struct.unpack_from('<I', data, img_offset + (i * 4))[0] for i in range(num_files)]

    for j in range(num_files):
        offset = offset_array[j]
        width, height = struct.unpack_from('<II', data, offset)
        offset += 8

        # Robust zlib slice sizing: last file boundary spans strictly to EOF
        if j == num_files - 1:
            zsize = len(data) - offset
        else:
            zsize = (offset_array[j+1] - offset_array[j]) - 8

        zlib_image = data[offset:offset + zsize]
        
        try:
            decompressed = zlib.decompress(zlib_image)
        except zlib.error:
            # Safe fall-back chunk parsing to discard container metadata trailing padding
            dec = zlib.decompressobj()
            decompressed = dec.decompress(zlib_image)
        
        is_prem = j in premultiplied_images
        img_res = load_mib2_to_rgb(width, height, decompressed, is_premultiplied=is_prem)
        
        out_img_path = os.path.join(out_dir, f'img_{str(j).zfill(2)}.png')
        img_res.save(out_img_path, 'PNG')
        print(f"    - Exported: {out_img_path} ({width}x{height}) {'[RGBA Premultiplied]' if is_prem else '[RGB]'}")


# ==============================================================================
#                          MAIN ENTRY POINT
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Combined Industrial MIB2STD Boot Tool. Supports unpacking and packing boot files."
    )
    subparsers = parser.add_subparsers(dest="mode", required=True, help="Working mode")

    # Pack command (pack)
    pack_parser = subparsers.add_parser("pack", help="Pack asset directory into .boot file")
    pack_parser.add_argument("folder", help="Path to the folder with script.txt and PNG assets")
    pack_parser.add_argument("output", help="Name of the output binary file (e.g. startup.boot)")
    pack_parser.add_argument(
        "--bits", type=int, choices=range(1, 9), default=None, 
        help="Reduce color depth for aggressive compression (1-8)"
    )

    # Unpack command (unpack)
    unpack_parser = subparsers.add_parser("unpack", help="Unpack .boot file into asset directory")
    unpack_parser.add_argument("file", help="Path to the binary .boot file")
    unpack_parser.add_argument(
        "outdir", nargs="?", default=None, 
        help="Target output directory (default: filename without extension)"
    )

    args = parser.parse_args()

    if args.mode == "pack":
        pack_boot(args.folder, args.output, color_bits=args.bits)
    elif args.mode == "unpack":
        output_dir = args.outdir if args.outdir else os.path.splitext(args.file)[0]
        unpack_boot(args.file, output_dir)
        print("[+] Done!")

if __name__ == "__main__":
    main()
