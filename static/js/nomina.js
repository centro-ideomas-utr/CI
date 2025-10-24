// Datos de ejemplo (puedes traerlos de una API o archivo JSON)
const nominaData = {
  empleado: "Jorge Enrique Gallegos Perez",
  infoLeft: [
    { label: "RFC emisor", value: "DADS870922QK2" },
    { label: "Nombre emisor", value: "SALVADOR DAVILA DUEÑAS" },
    { label: "RFC receptor", value: "UTR130212KB3" },
    { label: "Nombre receptor", value: "UNIVERSIDAD TECNOLOGICA EL RETOÑO" },
    { label: "Código postal del receptor", value: "20337" },
    { label: "Régimen fiscal receptor", value: "Personas Morales con Fines no Lucrativos" },
    { label: "Uso CFDI", value: "Gastos en general" }
  ],
  infoRight: [
    { label: "Folio fiscal", value: "4E83D82E-EA32-40FD-ABE6-24433F2CFC98" },
    { label: "No. de serie del CSD", value: "00001000000704534358" },
    { label: "Código postal, fecha y hora de emisión", value: "20722 2024-02-21 19:17:07" },
    { label: "Efecto de comprobante", value: "Ingreso" },
    { label: "Régimen fiscal", value: "Régimen Simplificado de Confianza" },
    { label: "Exportación", value: "No aplica" }
  ],
  conceptos: [
    {
      clave: "86111702",
      identificacion: "36.00",
      cantidad: "E48",
      unidad: "Unidad de servicio",
      valorUnitario: "105.00",
      importe: "3,780.00",
      descuento: "",
      objetoImpuesto: "Si objeto de impuesto.",
      descripcion: "Servicios profesionales por Curso en el Centro de Idiomas UTR correspondientes al mes de febrero 2024"
    }
  ],
  impuestos: [
    { impuesto: "IVA", tipo: "Traslado", base: "3,780.00", factor: "Tasa", tasa: "16.00%", importe: "604.80" },
    { impuesto: "ISR", tipo: "Retención", base: "3,780.00", factor: "Tasa", tasa: "1.25%", importe: "47.25" }
  ],
  totales: {
    moneda: "Peso Mexicano",
    formaPago: "Transferencia electrónica de fondos (incluye SPEI)",
    metodoPago: "Pago en una sola exhibición",
    subtotal: "$3,780.00",
    trasladados: "$604.80",
    retenidos: "$47.25",
    total: "$4,337.55"
  }
};

// === Renderizado dinámico ===
document.getElementById("empleadoNombre").textContent = nominaData.empleado;

// Info
const leftDiv = document.getElementById("info-left");
const rightDiv = document.getElementById("info-right");

nominaData.infoLeft.forEach(item => {
  leftDiv.innerHTML += `<p><strong>${item.label}:</strong> ${item.value}</p>`;
});

nominaData.infoRight.forEach(item => {
  rightDiv.innerHTML += `<p><strong>${item.label}:</strong> ${item.value}</p>`;
});

// Conceptos
const conceptosBody = document.querySelector("#conceptosTable tbody");
nominaData.conceptos.forEach(c => {
  conceptosBody.innerHTML += `
    <tr>
      <td>${c.clave}</td>
      <td>${c.identificacion}</td>
      <td>${c.cantidad}</td>
      <td>${c.cantidad}</td>
      <td>${c.unidad}</td>
      <td>${c.valorUnitario}</td>
      <td>${c.importe}</td>
      <td>${c.descuento}</td>
      <td>${c.objetoImpuesto}</td>
    </tr>
    <tr>
      <td colspan="9" class="desc">${c.descripcion}</td>
    </tr>
  `;
});

// Impuestos
const impuestosBody = document.querySelector("#impuestosTable tbody");
nominaData.impuestos.forEach(i => {
  impuestosBody.innerHTML += `
    <tr>
      <td>${i.impuesto}</td>
      <td>${i.tipo}</td>
      <td>${i.base}</td>
      <td>${i.factor}</td>
      <td>${i.tasa}</td>
      <td>${i.importe}</td>
    </tr>
  `;
});

// Totales
const totalesDiv = document.getElementById("totales");
totalesDiv.innerHTML = `
  <p><strong>Moneda:</strong> ${nominaData.totales.moneda}</p>
  <p><strong>Forma de pago:</strong> ${nominaData.totales.formaPago}</p>
  <p><strong>Método de pago:</strong> ${nominaData.totales.metodoPago}</p>
  <br>
  <p><strong>Subtotal:</strong> ${nominaData.totales.subtotal}</p>
  <p><strong>Impuestos trasladados (IVA 16%):</strong> ${nominaData.totales.trasladados}</p>
  <p><strong>Impuestos retenidos (ISR):</strong> ${nominaData.totales.retenidos}</p>
  <p class="total"><strong>Total: ${nominaData.totales.total}</strong></p>
`;
