# Visual ZPL Designer

A web-based WYSIWYG (What You See Is What You Get) editor for creating Zebra Programming Language (ZPL) labels.

## Features
- **Drag & Drop:** Drag elements (Text, Barcode, QR Code, Box) from the toolbox to the canvas.
- **Visual Editing:** Move elements around the label canvas.
- **Properties Panel:** Click any element to edit its properties:
  - **Text:** Change content, font height, and width.
  - **Barcode:** Change content and height.
  - **Box:** Change width, height, and thickness.
- **Real-time ZPL:** The ZPL code is generated instantly as you design.

## How to Run
Simply open `index.html` in any modern web browser.

## ZPL Logic & Algorithm

This tool uses a coordinate-based mapping algorithm to translate HTML DOM elements into ZPL commands.

### 1. Coordinate System
The canvas treats **1 pixel = 1 dot**.
- HTML `left` (x) -> ZPL `^FOx,y` (Field Origin X)
- HTML `top` (y) -> ZPL `^FOx,y` (Field Origin Y)

### 2. Element Mapping

| Element | HTML Representation | ZPL Command | Parameters |
|---------|---------------------|-------------|------------|
| **Text** | `<div>` with text | `^A0N,h,w` | Uses Scalable Font 0. `h`=Height, `w`=Width. |
| **Barcode** | `<div>` with striped bg | `^BCN,h,...` | Uses Code 128 (`^BC`). `h`=Height. |
| **QR Code** | `<div>` with SVG bg | `^BQN,2,4` | Uses QR Code (`^BQ`). Fixed magnification 4. |
| **Box** | `<div>` with border | `^GBw,h,t` | Uses Graphic Box (`^GB`). `w`=Width, `h`=Height, `t`=Thickness. |

### 3. Structure
Every label starts with `^XA` (Start Format) and ends with `^XZ` (End Format).
Label dimensions are set using `^PW` (Print Width) and `^LL` (Label Length).
