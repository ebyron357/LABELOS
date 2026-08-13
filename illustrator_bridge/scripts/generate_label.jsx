# LABELOS Illustrator ExtendScript
# Invoked via DoJavaScriptFile with payload JSON path as argument[0].
# Replaces named text frames / content by stable object names.
# Never unlocks or edits layers listed in payload.lockedLayerNames.

#target illustrator

function readFile(path) {
  var file = new File(path);
  if (!file.exists) {
    throw new Error("Payload file missing: " + path);
  }
  file.open("r");
  var content = file.read();
  file.close();
  return content;
}

function writeFile(path, content) {
  var file = new File(path);
  file.open("w");
  file.write(content);
  file.close();
}

function escapeJson(value) {
  return String(value)
    .replace(/\\/g, "\\\\")
    .replace(/"/g, '\\"')
    .replace(/\r/g, "\\r")
    .replace(/\n/g, "\\n");
}

function isLockedLayer(layer, lockedNames) {
  for (var i = 0; i < lockedNames.length; i++) {
    if (layer.name === lockedNames[i]) {
      return true;
    }
  }
  return layer.locked || !layer.visible;
}

function replaceInItems(items, variables, locked) {
  var updated = 0;
  for (var i = 0; i < items.length; i++) {
    var item = items[i];
    if (locked) {
      continue;
    }
    if (item.typename === "TextFrame") {
      var name = item.name;
      if (variables.hasOwnProperty(name)) {
        item.contents = variables[name];
        updated++;
      }
    } else if (item.typename === "GroupItem") {
      updated += replaceInItems(item.pageItems, variables, locked);
    }
  }
  return updated;
}

function exportOutputs(doc, outputDir, formats, baseName) {
  var outputs = [];
  for (var i = 0; i < formats.length; i++) {
    var fmt = String(formats[i]).toLowerCase();
    var target;
    if (fmt === "pdf") {
      target = new File(outputDir + "/" + baseName + ".pdf");
      var pdfOptions = new PDFSaveOptions();
      pdfOptions.compatibility = PDFCompatibility.ACROBAT5;
      doc.saveAs(target, pdfOptions);
      outputs.push({ file: target.name, path: target.fsName, format: "pdf" });
    } else if (fmt === "ai") {
      target = new File(outputDir + "/" + baseName + ".ai");
      var aiOptions = new IllustratorSaveOptions();
      doc.saveAs(target, aiOptions);
      outputs.push({ file: target.name, path: target.fsName, format: "ai" });
    } else if (fmt === "png") {
      target = new File(outputDir + "/" + baseName + ".png");
      var pngOptions = new ExportOptionsPNG24();
      pngOptions.artBoardClipping = true;
      doc.exportFile(target, ExportType.PNG24, pngOptions);
      outputs.push({ file: target.name, path: target.fsName, format: "png" });
    }
  }
  return outputs;
}

function main() {
  var payloadPath = arguments && arguments.length ? arguments[0] : null;
  if (!payloadPath) {
    throw new Error("Missing payload path argument");
  }
  var payload = eval("(" + readFile(payloadPath) + ")");
  var resultPath = payload.resultPath;
  try {
    var template = new File(payload.templatePath);
    if (!template.exists) {
      throw new Error("Template missing: " + payload.templatePath);
    }
    var doc = app.open(template);
    var lockedNames = payload.lockedLayerNames || [];
    var updated = 0;
    for (var li = 0; li < doc.layers.length; li++) {
      var layer = doc.layers[li];
      var locked = isLockedLayer(layer, lockedNames);
      updated += replaceInItems(layer.pageItems, payload.variables || {}, locked);
    }

    // Optional: if a text frame named UPC / QR_CODE exists, set contents to code values.
    if (payload.barcodeValue) {
      payload.variables = payload.variables || {};
      payload.variables.UPC = payload.barcodeValue;
    }
    if (payload.qrValue) {
      payload.variables = payload.variables || {};
      payload.variables.QR_CODE = payload.qrValue;
    }

    var outputDir = payload.outputDir;
    var baseName = template.name.replace(/\.[^.]+$/, "");
    var outputs = exportOutputs(doc, outputDir, payload.exportFormats || ["pdf"], baseName);
    doc.close(SaveOptions.DONOTSAVECHANGES);

    var parts = [];
    parts.push('"success": true');
    parts.push('"code": "OK"');
    parts.push('"message": "Generated ' + updated + ' variable replacements"');
    parts.push('"updatedCount": ' + updated);
    var outJson = [];
    for (var oi = 0; oi < outputs.length; oi++) {
      outJson.push(
        '{"file":"' +
          escapeJson(outputs[oi].file) +
          '","path":"' +
          escapeJson(outputs[oi].path) +
          '","format":"' +
          escapeJson(outputs[oi].format) +
          '"}'
      );
    }
    parts.push('"outputs": [' + outJson.join(",") + "]");
    writeFile(resultPath, "{" + parts.join(",") + "}");
  } catch (error) {
    writeFile(
      resultPath,
      '{"success": false, "code": "ILLUSTRATOR_SCRIPT_FAILED", "message": "' +
        escapeJson(error.message || error) +
        '"}'
    );
  }
}

main();
