const textDisplay = document.getElementById("textDisplay");
const failureModeBox = document.getElementById("failureMode");
const productSelect = document.getElementById("product");
const modelSelect = document.getElementById("model");
const stationSelect = document.getElementById("station");
const serialInput = document.getElementById("serial_number");
const poInput = document.getElementById("po");
const endorseBtn = document.getElementById("endorseBtn");
const toast = document.getElementById("toast");

// Tracks whether the currently-entered serial has been confirmed to exist
// in <product>.<model>_<station>. Reset any time product/model/station/serial changes.
let serialValidated = false;

function setText(msg) {
  textDisplay.textContent = msg;
}

function showToast(message, kind) {
  toast.textContent = message;
  toast.className = `toast show ${kind}`;
  setTimeout(() => { toast.className = "toast"; }, 3500);
}

function fillSelect(select, values, placeholder) {
  select.innerHTML = "";
  const opt0 = document.createElement("option");
  opt0.value = "";
  opt0.textContent = placeholder;
  select.appendChild(opt0);
  values.forEach(v => {
    const opt = document.createElement("option");
    opt.value = v;
    opt.textContent = v;
    select.appendChild(opt);
  });
}

function resetSerialValidation() {
  serialValidated = false;
  poInput.value = "";
  failureModeBox.value = "";
}

async function loadProducts() {
  try {
    const res = await fetch("/api/products");
    const data = await res.json();
    fillSelect(productSelect, data, "Select product");
  } catch (e) {
    fillSelect(productSelect, [], "Unavailable");
  }
}

async function loadModels(product) {
  if (!product) {
    fillSelect(modelSelect, [], "Select product first");
    fillSelect(stationSelect, [], "Select model first");
    return;
  }
  try {
    const res = await fetch(`/api/models?product=${encodeURIComponent(product)}`);
    const data = await res.json();
    fillSelect(modelSelect, data, "Select model");
  } catch (e) {
    fillSelect(modelSelect, [], "Unavailable");
  }
  fillSelect(stationSelect, [], "Select model first");
}

async function loadStations(product, model) {
  if (!product || !model) {
    fillSelect(stationSelect, [], "Select model first");
    return;
  }
  try {
    const res = await fetch(
      `/api/stations?product=${encodeURIComponent(product)}&model=${encodeURIComponent(model)}`
    );
    const data = await res.json();
    fillSelect(stationSelect, data, "Select station");
  } catch (e) {
    fillSelect(stationSelect, [], "Unavailable");
  }
}

async function lookupSerial(serial) {
  if (!serial) return;
  try {
    const res = await fetch(`/api/lookup_serial?serial=${encodeURIComponent(serial)}`);
    const data = await res.json();
    if (data.found) {
      if (data.product) {
        productSelect.value = data.product;
        await loadModels(data.product);
      }
      if (data.model) {
        modelSelect.value = data.model;
        await loadStations(data.product, data.model);
      }
      if (data.station) stationSelect.value = data.station;
      failureModeBox.value = data.failure_mode || "";
      poInput.value = data.po || "";
      setText(`Existing FA case found for serial ${serial}. Review and re-endorse if needed.`);
    } else {
      failureModeBox.value = "";
      setText(`New serial ${serial}. Fill in the details and endorse to FA.`);
    }
  } catch (e) {
    setText("Could not reach the server to look up this serial number.");
  }
}

// Confirms the serial is a known unit by checking <product>.<model>_<station>.
// Requires product + model + station to already be selected.
async function checkSerialInMain(product, model, station, serial) {
  if (!product || !model || !station || !serial) {
    resetSerialValidation();
    return;
  }
  try {
    const res = await fetch(
      `/api/check_serial_main?product=${encodeURIComponent(product)}&model=${encodeURIComponent(model)}&station=${encodeURIComponent(station)}&serial=${encodeURIComponent(serial)}`
    );
    const data = await res.json();

    if (data.found) {
      serialValidated = true;
      poInput.value = data.po_num || "";
      failureModeBox.value = data.fail_reason || "";
      setText(`Serial ${serial} found in ${data.table_checked}. PO and failure mode auto-filled. Ready to endorse.`);
      return;
    }

    serialValidated = false;
    poInput.value = "";
    failureModeBox.value = "";
    const reason = data.table_exists
      ? `No record found for serial ${serial} in ${data.table_checked}.`
      : `Table ${data.table_checked} does not exist.`;
    setText(reason);
    showToast(reason, "error");
  } catch (e) {
    serialValidated = false;
    poInput.value = "";
    failureModeBox.value = "";
    setText("Could not reach the server to validate this serial number.");
  }
}

async function handleSerialEntry() {
  const serial = serialInput.value.trim();
  if (!serial) {
    resetSerialValidation();
    return;
  }
  await lookupSerial(serial);
  await checkSerialInMain(productSelect.value, modelSelect.value, stationSelect.value, serial);
}

productSelect?.addEventListener("change", () => {
  resetSerialValidation();
  loadModels(productSelect.value);
});
modelSelect?.addEventListener("change", () => {
  resetSerialValidation();
  loadStations(productSelect.value, modelSelect.value);
});
stationSelect?.addEventListener("change", () => {
  resetSerialValidation();
});

serialInput.addEventListener("input", resetSerialValidation);
serialInput.addEventListener("blur", handleSerialEntry);
serialInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    handleSerialEntry();
  }
});

endorseBtn.addEventListener("click", async () => {
  const payload = {
    serial_number: serialInput.value.trim(),
    product: productSelect.value,
    model: modelSelect.value,
    station: stationSelect.value,
    failure_mode: failureModeBox.value.trim(),
    po: poInput.value.trim(),
  };

  if (!payload.serial_number) {
    setText("Please enter a serial number before endorsing.");
    return;
  }
  if (!payload.product || !payload.model || !payload.station) {
    setText("Please select a product, model, and station before endorsing.");
    return;
  }

  // Client-side gate: re-validate if the serial hasn't been confirmed yet
  // (e.g. user edited the serial after it was validated).
  if (!serialValidated) {
    await checkSerialInMain(payload.product, payload.model, payload.station, payload.serial_number);
    if (!serialValidated) {
      return; // checkSerialInMain already showed the reason
    }
  }

  endorseBtn.disabled = true;
  try {
    // Server re-checks <product>.<model>_<station> again on submit, so this
    // stays authoritative even if someone bypasses the client-side check.
    const res = await fetch("/api/endorse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (data.success) {
      showToast(data.message, "success");
      setText("Endorsed. Please enter the next serial number.");
      serialInput.value = "";
      poInput.value = "";
      failureModeBox.value = "";
      resetSerialValidation();
    } else {
      showToast(data.message, "error");
      setText(data.message);
    }
  } catch (e) {
    showToast("Could not reach the server.", "error");
  } finally {
    endorseBtn.disabled = false;
  }
});

poInput.readOnly = true;
poInput.placeholder = "Auto-filled from serial lookup";
failureModeBox.readOnly = true;
failureModeBox.placeholder = "Auto-filled from serial lookup";

loadProducts();
fillSelect(modelSelect, [], "Select product first");
fillSelect(stationSelect, [], "Select model first");