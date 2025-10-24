        document.addEventListener('DOMContentLoaded', function() {
            // Datos de ejemplo para la nómina
            const nominaData = {
                nombre: "Laura Martínez",
                infoIzquierda: [
                    "<strong>RFC:</strong> LOML850515ABC",
                    "<strong>CURP:</strong> LOML850515XYZ",
                    "<strong>NSS:</strong> 1234567890"
                ],
                infoDerecha: [
                    "<strong>Periodo:</strong> 01/03/2024 - 15/03/2024",
                    "<strong>Días pagados:</strong> 15",
                    "<strong>Puesto:</strong> Docente de Idiomas"
                ],
                conceptos: [
                    { clave: '84111505', noId: 'P01', cantidad: 1, claveUnidad: 'ACT', unidad: 'Actividad', valor: 5000.00, importe: 5000.00, descuento: 0.00, objetoImp: '02' },
                    { clave: '84111506', noId: 'B01', cantidad: 1, claveUnidad: 'ACT', unidad: 'Actividad', valor: 500.00, importe: 500.00, descuento: 0.00, objetoImp: '02' }
                ],
                impuestos: [
                    { impuesto: '002', tipo: 'Retención', base: 5500.00, tipoFactor: 'Tasa', tasaCuota: 0.10, importe: 550.00 },
                    { impuesto: '001', tipo: 'Retención', base: 5500.00, tipoFactor: 'Tasa', tasaCuota: 0.08, importe: 440.00 }
                ]
            };

            // Poblar información del docente
            document.getElementById('info-left').innerHTML = nominaData.infoIzquierda.map(p => `<p>${p}</p>`).join('');
            document.getElementById('info-right').innerHTML = nominaData.infoDerecha.map(p => `<p>${p}</p>`).join('');

            // Poblar tabla de conceptos
            const conceptosTbody = document.querySelector('#conceptosTable tbody');
            nominaData.conceptos.forEach(c => {
                const row = conceptosTbody.insertRow();
                row.innerHTML = `
                    <td>${c.clave}</td>
                    <td>${c.noId}</td>
                    <td>${c.cantidad}</td>
                    <td>${c.claveUnidad}</td>
                    <td>${c.unidad}</td>
                    <td>$${c.valor.toFixed(2)}</td>
                    <td>$${c.importe.toFixed(2)}</td>
                    <td>$${c.descuento.toFixed(2)}</td>
                    <td>${c.objetoImp}</td>
                `;
            });

            // Poblar tabla de impuestos
            const impuestosTbody = document.querySelector('#impuestosTable tbody');
            nominaData.impuestos.forEach(i => {
                const row = impuestosTbody.insertRow();
                row.innerHTML = `
                    <td>${i.impuesto}</td>
                    <td>${i.tipo}</td>
                    <td>$${i.base.toFixed(2)}</td>
                    <td>${i.tipoFactor}</td>
                    <td>${i.tasaCuota.toFixed(4)}</td>
                    <td>$${i.importe.toFixed(2)}</td>
                `;
            });

            // Calcular y mostrar totales
            const subtotal = nominaData.conceptos.reduce((acc, c) => acc + c.importe, 0);
            const totalImpuestos = nominaData.impuestos.reduce((acc, i) => acc + i.importe, 0);
            const total = subtotal - totalImpuestos;
            
            document.getElementById('totales').innerHTML = `
                <p><strong>Subtotal:</strong> $${subtotal.toFixed(2)}</p>
                <p><strong>Total Impuestos Retenidos:</strong> $${totalImpuestos.toFixed(2)}</p>
                <p class="total"><strong>Neto a Pagar:</strong> $${total.toFixed(2)}</p>
            `;
        });

    // --- Lógica para el menú lateral (Sidebar) ---
    const menuIcon = document.getElementById('menu-icon');
    const sidebar = document.getElementById('sidebar');
    const pageContent = document.querySelector('.page-content');

    // Verifica que los elementos del menú existan antes de agregar el evento
    if (menuIcon && sidebar && pageContent) {
        menuIcon.addEventListener('click', () => {
            // Agrega o quita la clase 'active' del sidebar para mostrarlo u ocultarlo
            sidebar.classList.toggle('active');
            
            // Empuja el contenido principal cuando el menú se abre o cierra
            if (sidebar.classList.contains('active')) {
                pageContent.style.marginLeft = '230px';
            } else {
                pageContent.style.marginLeft = '0';
            }
        });
    
        }