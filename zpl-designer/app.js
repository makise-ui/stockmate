document.addEventListener('DOMContentLoaded', () => {

    const INITIAL_ZPL = `^XA^PW830^LL176
^FX --- LEFT SIDE: Samsung (ID 101) --- ^FS
^FO0,10^A0N,30,30
^FB400,1,0,C,0^FD4bros mobile^FS
^FO95,42^BY3,2,40^BCN,40,N,N,N^FD101^FS
^FO330,45^GB50,32,32^FS
^FO330,49^A0N,24,24^FR^FB50,1,0,C,0^FDA1^FS
^FO0,85^A0N,25,25^FB400,1,0,C,0^FD101^FS
^FO25,112^A0N,29,29^FB350,2,0,L,0^FDSamsung Galaxy A54 5G^FS
^FO25,145^A0N,26,26^FB200,1,0,L,0^FD8/128 GB^FS
^FO150,142^A0N,32,32^FB240,1,0,R,0^FDRs. 32,000^FS

^FX --- RIGHT SIDE: Motorola (ID 102) --- ^FS
^FO416,10^A0N,30,30^FB400,1,0,C,0^FD4bros mobile^FS
^FO511,42^BY3,2,40^BCN,40,N,N,N^FD102^FS
^FO740,45^GB50,32,32^FS
^FO740,49^A0N,24,24^FR^FB50,1,0,C,0^FDA1^FS
^FO416,85^A0N,25,25^FB400,1,0,C,0^FD102^FS
^FO441,112^A0N,29,29^FB350,2,0,L,0^FDMotorola Moto G54 Power^FS
^FO441,145^A0N,26,26^FB200,1,0,L,0^FD12/256 GB^FS
^FO566,142^A0N,32,32^FB240,1,0,R,0^FDRs. 18,500^FS
^XZ`;

    // --- State ---
    const state = {
        elements: [],
        selectedId: null,
        draggingId: null,
        resizingId: null, // New: Tracking resize
        dragOffsetX: 0,
        dragOffsetY: 0,
        initialResizeW: 0,
        initialResizeH: 0,
        initialMouseX: 0,
        initialMouseY: 0,
        canvasWidth: 800,
        canvasHeight: 600
    };

    // --- DOM Elements ---
    const canvas = document.getElementById('zpl-canvas');
    const zplOutput = document.getElementById('zpl-output');
    const propForm = document.getElementById('properties-form');
    const noSelectionMsg = document.getElementById('no-selection-msg');
    const propPanel = document.querySelector('.properties-panel');

    // Inputs
    const inputX = document.getElementById('prop-x');
    const inputY = document.getElementById('prop-y');
    const inputText = document.getElementById('prop-text');
    const inputFontH = document.getElementById('prop-font-height');
    const inputFontW = document.getElementById('prop-font-width');
    const inputWidth = document.getElementById('prop-width');
    const inputHeight = document.getElementById('prop-height');
    const inputThickness = document.getElementById('prop-thickness');

    // Groups
    const groupText = document.getElementById('group-text');
    const groupFont = document.getElementById('group-font');
    const groupDims = document.getElementById('group-dims');

    // Inject Sliders and Bold Toggle
    function injectControls() {
        // Helper to turn an input into a slider combo
        const enhanceInput = (input, min, max) => {
            if (input.dataset.enhanced) return; // Prevent double inject
            const wrapper = document.createElement('div');
            wrapper.className = 'slider-container';
            input.parentNode.insertBefore(wrapper, input);
            wrapper.appendChild(input);

            const slider = document.createElement('input');
            slider.type = 'range';
            slider.min = min;
            slider.max = max;
            slider.className = 'prop-slider';
            wrapper.insertBefore(slider, input); // Slider first

            // Sync
            slider.addEventListener('input', () => { input.value = slider.value; input.dispatchEvent(new Event('input')); });
            input.addEventListener('input', () => { slider.value = input.value; });

            input.dataset.enhanced = "true";
        };

        enhanceInput(inputFontH, 10, 200);
        enhanceInput(inputFontW, 10, 200);
        enhanceInput(inputWidth, 0, 800);
        enhanceInput(inputHeight, 0, 600);

        // Add Bold Toggle & Align if missing
        if (!document.getElementById('prop-bold')) {
            const boldDiv = document.createElement('div');
            boldDiv.className = 'form-group checkbox-group';
            boldDiv.id = 'group-bold';
            boldDiv.innerHTML = `
                <input type="checkbox" id="prop-bold">
                <label for="prop-bold">Bold Text (CSS)</label>
            `;
            groupFont.after(boldDiv);
        }

        if (!document.getElementById('prop-align')) {
            const alignDiv = document.createElement('div');
            alignDiv.className = 'form-group';
            alignDiv.id = 'group-align';
            alignDiv.innerHTML = `
                <label for="prop-align">Alignment:</label>
                <select id="prop-align">
                    <option value="L">Left</option>
                    <option value="C">Center</option>
                    <option value="R">Right</option>
                    <option value="J">Justified</option>
                </select>
            `;
            document.getElementById('group-bold').after(alignDiv);

            const invertDiv = document.createElement('div');
            invertDiv.className = 'form-group checkbox-group';
            invertDiv.id = 'group-invert';
            invertDiv.innerHTML = `
                <input type="checkbox" id="prop-invert">
                <label for="prop-invert">Invert Color (^FR)</label>
            `;
            alignDiv.after(invertDiv);
        }
    }
    injectControls();

    const inputBold = document.getElementById('prop-bold');
    const inputAlign = document.getElementById('prop-align');
    const inputInvert = document.getElementById('prop-invert');

    // --- Toolbox ---
    const toolItems = document.querySelectorAll('.tool-item');
    toolItems.forEach(item => {
        item.addEventListener('click', () => {
             const type = item.dataset.type;
             createElement(type, 50, 50);
        });
        item.addEventListener('dragstart', (e) => {
            e.dataTransfer.setData('type', item.dataset.type);
            e.dataTransfer.effectAllowed = 'copy';
        });
    });

    canvas.addEventListener('dragover', (e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; });
    canvas.addEventListener('drop', (e) => {
        e.preventDefault();
        const type = e.dataTransfer.getData('type');
        if (type) {
            const rect = canvas.getBoundingClientRect();
            createElement(type, Math.round(e.clientX - rect.left), Math.round(e.clientY - rect.top));
        }
    });

    // --- Interaction (Drag & Resize) ---
    const getClientXY = (e) => {
        return {
            x: e.touches ? e.touches[0].clientX : e.clientX,
            y: e.touches ? e.touches[0].clientY : e.clientY
        };
    }

    const handleStart = (e) => {
        // Check for resize handle first
        if (e.target.classList.contains('resize-handle')) {
            e.preventDefault();
            e.stopPropagation();
            const elId = parseInt(e.target.closest('.canvas-element').dataset.id);
            state.resizingId = elId;
            const el = state.elements.find(i => i.id === elId);

            const xy = getClientXY(e);
            state.initialMouseX = xy.x;
            state.initialMouseY = xy.y;

            // Store initial dimensions based on type
            if (el.type === 'text') {
                state.initialResizeH = el.fontHeight;
                state.initialResizeW = el.fontWidth; // We resize font size
            } else if (el.type === 'box') {
                state.initialResizeW = el.width;
                state.initialResizeH = el.height;
            } else if (el.type === 'barcode') {
                state.initialResizeH = el.fontHeight; // Height
                state.initialResizeW = el.width; // Width
            }
            return;
        }

        const target = e.target.closest('.canvas-element');
        if (target) {
            e.preventDefault();
            const id = parseInt(target.dataset.id);
            selectElement(id);
            state.draggingId = id;
            const el = state.elements.find(i => i.id === id);
            const rect = canvas.getBoundingClientRect();
            const xy = getClientXY(e);
            state.dragOffsetX = (xy.x - rect.left) - el.x;
            state.dragOffsetY = (xy.y - rect.top) - el.y;
        } else {
             deselectAll();
        }
    };

    const handleMove = (e) => {
        const xy = getClientXY(e);

        // Resizing Logic
        if (state.resizingId !== null) {
            e.preventDefault();
            const deltaX = xy.x - state.initialMouseX;
            const deltaY = xy.y - state.initialMouseY;
            const el = state.elements.find(i => i.id === state.resizingId);

            if (el.type === 'text') {
                // Resize Font
                // Just use Y delta for height, and scale width proportionally
                let newH = Math.max(10, state.initialResizeH + deltaY);
                let ratio = state.initialResizeW / state.initialResizeH;
                el.fontHeight = Math.round(newH);
                el.fontWidth = Math.round(newH * ratio);
                inputFontH.value = el.fontHeight;
                inputFontW.value = el.fontWidth;
            } else if (el.type === 'box') {
                el.width = Math.max(10, state.initialResizeW + deltaX);
                el.height = Math.max(10, state.initialResizeH + deltaY);
                inputWidth.value = el.width;
                inputHeight.value = el.height;
            } else if (el.type === 'barcode') {
                 // Resize Height only typically, or width?
                 // Let's map Y to height, X to visual width
                 el.fontHeight = Math.max(10, state.initialResizeH + deltaY);
                 el.width = Math.max(50, state.initialResizeW + deltaX);
                 inputFontH.value = el.fontHeight;
                 // inputWidth.value = el.width; // Not usually exposed for barcode but internal
            }

            renderElement(el);
            generateZPL(); // Live update
            return;
        }

        // Dragging Logic
        if (state.draggingId !== null) {
            e.preventDefault();
            const rect = canvas.getBoundingClientRect();
            let newX = (xy.x - rect.left) - state.dragOffsetX;
            let newY = (xy.y - rect.top) - state.dragOffsetY;
            updateElementPosition(state.draggingId, Math.round(newX), Math.round(newY));
        }
    };

    const handleEnd = () => {
        state.draggingId = null;
        state.resizingId = null;
    };

    canvas.addEventListener('mousedown', handleStart);
    canvas.addEventListener('touchstart', handleStart, {passive: false});
    window.addEventListener('mousemove', handleMove);
    window.addEventListener('touchmove', handleMove, {passive: false});
    window.addEventListener('mouseup', handleEnd);
    window.addEventListener('touchend', handleEnd);


    // --- Core Functions ---

    function createElement(type, x, y, props = {}) {
        const id = Date.now() + Math.floor(Math.random() * 1000);
        const newEl = {
            id: id, type: type, x: x, y: y,
            data: type === 'text' ? 'Text' : (type === 'barcode' ? '123' : ''),
            fontHeight: 30, fontWidth: 30,
            width: 0, height: 100, thickness: 1,
            align: 'L', invert: false, bold: false, // New Bold prop
            ...props
        };
        if (type === 'box' && newEl.width === 0) newEl.width = 100;

        state.elements.push(newEl);
        renderElement(newEl);
        selectElement(id);
        generateZPL();
        return newEl;
    }

    function renderElement(el) {
        let div = document.querySelector(`.canvas-element[data-id="${el.id}"]`);
        if (!div) {
            div = document.createElement('div');
            div.className = `canvas-element el-${el.type}`;
            div.dataset.id = el.id;
            // Add Resize Handle
            const handle = document.createElement('div');
            handle.className = 'resize-handle';
            div.appendChild(handle);
            canvas.appendChild(div);
        }

        div.style.left = `${el.x}px`;
        div.style.top = `${el.y}px`;

        if (el.invert) div.classList.add('inverted'); else div.classList.remove('inverted');

        // Bold Visual
        if (el.bold) div.classList.add('bold-style'); else div.classList.remove('bold-style');

        if (el.type === 'text') {
            div.firstChild.textContent = el.data; // Use firstChild text node to not kill handle
            if (!div.firstChild || div.firstChild.nodeType !== 3) div.prepend(document.createTextNode(el.data));
            div.childNodes[0].nodeValue = el.data;

            div.style.fontSize = `${el.fontHeight}px`;
            const aspect = el.fontWidth / el.fontHeight;
            div.style.transform = `scaleX(${aspect})`;
            div.style.transformOrigin = 'left top';

            div.style.width = el.width > 0 ? `${el.width}px` : 'auto';
            div.style.textAlign = el.align === 'C' ? 'center' : (el.align === 'R' ? 'right' : 'left');

        } else if (el.type === 'barcode') {
            div.style.height = `${el.fontHeight}px`;
            div.style.width = el.width > 0 ? `${el.width}px` : '200px';
            // Update text content safely
             let txt = div.childNodes[0].nodeType === 3 ? div.childNodes[0] : null;
             if (!txt) { txt = document.createTextNode(el.data); div.prepend(txt); }
             txt.nodeValue = el.data;
            div.style.transform = 'none';
        } else if (el.type === 'box') {
            div.style.width = `${el.width}px`;
            div.style.height = `${el.height}px`;
            div.style.borderWidth = `${el.thickness}px`;
            div.style.transform = 'none';
        }

        if (state.selectedId === el.id) div.classList.add('selected'); else div.classList.remove('selected');
    }

    function updateElementPosition(id, x, y) {
        const el = state.elements.find(e => e.id === id);
        if (el) {
            el.x = x; el.y = y;
            renderElement(el);
            if (state.selectedId === id) { inputX.value = x; inputY.value = y; }
            generateZPL();
        }
    }

    function selectElement(id) {
        state.selectedId = id;
        state.elements.forEach(el => renderElement(el));
        const el = state.elements.find(e => e.id === id);
        if (!el) return;

        noSelectionMsg.style.display = 'none';
        propForm.style.display = 'block';
        propPanel.classList.add('open');

        document.getElementById('prop-type').textContent = el.type.toUpperCase();
        inputX.value = el.x;
        inputY.value = el.y;

        // Toggle groups
        const gBold = document.getElementById('group-bold');
        const gAlign = document.getElementById('group-align');
        const gInvert = document.getElementById('group-invert');

        if (el.type === 'text') {
            groupText.style.display = 'block'; groupFont.style.display = 'block'; groupDims.style.display = 'block';
            gBold.style.display = 'flex'; gAlign.style.display = 'block'; gInvert.style.display = 'flex';

            inputText.value = el.data;
            inputFontH.value = el.fontHeight; inputFontW.value = el.fontWidth;
            inputWidth.value = el.width; inputAlign.value = el.align;
            inputBold.checked = el.bold; inputInvert.checked = el.invert;

            // Sync sliders
            inputFontH.dispatchEvent(new Event('input'));
            inputFontW.dispatchEvent(new Event('input'));

        } else if (el.type === 'barcode') {
            groupText.style.display = 'block'; groupFont.style.display = 'block'; groupDims.style.display = 'none';
            gBold.style.display = 'none'; gAlign.style.display = 'none'; gInvert.style.display = 'none';
            inputText.value = el.data; inputFontH.value = el.fontHeight;
            inputFontH.dispatchEvent(new Event('input'));

        } else if (el.type === 'box') {
            groupText.style.display = 'none'; groupFont.style.display = 'none'; groupDims.style.display = 'block';
            gBold.style.display = 'none'; gAlign.style.display = 'none'; gInvert.style.display = 'none';
            inputWidth.value = el.width; inputHeight.value = el.height; inputThickness.value = el.thickness;
            inputWidth.dispatchEvent(new Event('input'));
            inputHeight.dispatchEvent(new Event('input'));
        }
    }

    function deselectAll() {
        state.selectedId = null;
        state.elements.forEach(el => renderElement(el));
        propPanel.classList.remove('open');
    }

    function removeElement(id) {
        state.elements = state.elements.filter(el => el.id !== id);
        const div = document.querySelector(`.canvas-element[data-id="${id}"]`);
        if (div) div.remove();
        deselectAll();
        generateZPL();
    }

    function updateSelectedProps() {
        if (!state.selectedId) return;
        const el = state.elements.find(e => e.id === state.selectedId);

        el.x = parseInt(inputX.value) || 0;
        el.y = parseInt(inputY.value) || 0;

        if (el.type === 'text' || el.type === 'barcode') el.data = inputText.value;

        if (el.type === 'text') {
            el.fontHeight = parseInt(inputFontH.value) || 10;
            el.fontWidth = parseInt(inputFontW.value) || 10;
            el.width = parseInt(inputWidth.value) || 0;
            el.align = inputAlign.value;
            el.bold = inputBold.checked;
            el.invert = inputInvert.checked;
        } else if (el.type === 'barcode') {
            el.fontHeight = parseInt(inputFontH.value) || 50;
        } else if (el.type === 'box') {
            el.width = parseInt(inputWidth.value) || 0;
            el.height = parseInt(inputHeight.value) || 0;
            el.thickness = parseInt(inputThickness.value) || 1;
        }

        renderElement(el);
        generateZPL();
    }

    [inputX, inputY, inputText, inputFontH, inputFontW, inputWidth, inputHeight, inputThickness, inputAlign, inputBold, inputInvert].forEach(input => {
        if (input) input.addEventListener('input', updateSelectedProps);
    });

    document.getElementById('delete-btn').addEventListener('click', () => { if (state.selectedId) removeElement(state.selectedId); });

    // --- ZPL Parser & Generator ---
    let debounceTimer;
    function generateZPL() {
        let zpl = `^XA^PW${state.canvasWidth}^LL${state.canvasHeight}\n\n`;
        state.elements.forEach(el => {
            zpl += `^FO${el.x},${el.y}`;
            if (el.type === 'text') {
                zpl += `^A0N,${el.fontHeight},${el.fontWidth}`;
                if (el.invert) zpl += `^FR`;
                if (el.width > 0 || el.align !== 'L') zpl += `^FB${el.width},1,0,${el.align},0`;
                zpl += `^FD${el.data}^FS\n`;
            } else if (el.type === 'barcode') {
                zpl += `^BY3,2,${el.fontHeight}^BCN,${el.fontHeight},N,N,N^FD${el.data}^FS\n`;
            } else if (el.type === 'box') {
                zpl += `^GB${el.width},${el.height},${el.thickness},B,0^FS\n`;
            }
        });
        zpl += '^XZ';
        zplOutput.value = zpl;

        clearTimeout(debounceTimer);
        document.getElementById('loading-text').textContent = "Updating preview...";
        document.getElementById('loading-text').style.display = "inline";
        debounceTimer = setTimeout(() => { updatePreviewImage(zpl); }, 1000);
    }

    function updatePreviewImage(zpl) {
        const width = Math.ceil(state.canvasWidth / 203);
        const height = Math.ceil(state.canvasHeight / 203);
        const url = `https://api.labelary.com/v1/printers/8dpmm/labels/${width}x${height}/0/`;

        fetch(url, { method: 'POST', body: zpl, headers: { 'Content-Type': 'application/x-www-form-urlencoded' } })
        .then(res => { if (res.ok) return res.blob(); throw new Error('Err'); })
        .then(blob => {
            document.getElementById('labelary-image').src = URL.createObjectURL(blob);
            document.getElementById('labelary-image').style.display = 'inline-block';
            document.getElementById('loading-text').style.display = 'none';
        })
        .catch(err => { document.getElementById('loading-text').textContent = "Preview Error"; });
    }

    // Parse logic (Updated to include bold/align defaults)
    function parseZPL(zplCode) {
        state.elements = []; canvas.innerHTML = '';
        let cleanZpl = zplCode.replace(/\\^FX.*?\\^FS/g, '');

        let curX=0, curY=0, curFontH=30, curFontW=30, curAlign='L', curBlockW=0, curInvert=false, curBarcodeH=50;
        let isBarcode = false;

        const matchPW = zplCode.match(/\\^PW(\\d+)/); if (matchPW) state.canvasWidth = parseInt(matchPW[1]);
        const matchLL = zplCode.match(/\\^LL(\\d+)/); if (matchLL) state.canvasHeight = parseInt(matchLL[1]);
        canvas.style.width = `${state.canvasWidth}px`; canvas.style.height = `${state.canvasHeight}px`;

        const tokens = zplCode.split('^').filter(t => t.trim().length > 0);
        tokens.forEach(token => {
            const cmd = token.substring(0, 2);
            const data = token.substring(2);
            const params = data.split(',');

            if (cmd === 'FO') { curX=parseInt(params[0])||0; curY=parseInt(params[1])||0; curInvert=false; curBlockW=0; curAlign='L'; }
            else if (cmd === 'A0') { curFontH=parseInt(params[1])||30; curFontW=parseInt(params[2])||30; }
            else if (cmd === 'BY') { if (params[2]) curBarcodeH=parseInt(params[2]); }
            else if (cmd === 'BC') { isBarcode=true; if (params[1]) curBarcodeH=parseInt(params[1]); }
            else if (cmd === 'FB') { curBlockW=parseInt(params[0])||0; if (params[3]) curAlign=params[3]; }
            else if (cmd === 'FR') { curInvert=true; }
            else if (cmd === 'GB') { createElement('box', curX, curY, { width: parseInt(params[0])||100, height: parseInt(params[1])||100, thickness: parseInt(params[2])||1 }); }
            else if (cmd === 'FD') {
                let content = data.split('^FS')[0];
                if (isBarcode) { createElement('barcode', curX, curY, { data: content, fontHeight: curBarcodeH }); isBarcode=false; }
                else { createElement('text', curX, curY, { data: content, fontHeight: curFontH, fontWidth: curFontW, width: curBlockW, align: curAlign, invert: curInvert }); }
            }
        });
        deselectAll();
    }

    document.getElementById('copy-zpl').addEventListener('click', () => { zplOutput.select(); document.execCommand('copy'); alert('Copied!'); });
    document.getElementById('preview-zpl').addEventListener('click', () => { parseZPL(zplOutput.value); });

    parseZPL(INITIAL_ZPL);
});
