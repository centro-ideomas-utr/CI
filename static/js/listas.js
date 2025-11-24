

    // --- Lógica del Sidebar ---
    if (menuIcon && sidebar && pageContent) {
        menuIcon.addEventListener('click', () => {
            sidebar.classList.toggle('active');
            if (sidebar.classList.contains('active')) {
                pageContent.style.marginLeft = '230px';
            } else {
                pageContent.style.marginLeft = '0';
            }
        });
    }

function fetchAsistencias(fechas) {
        const groupId = document.getElementById('current-group-id').value; // Obtener ID

        fetch('/api/obtener_asistencias', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                fechas: fechas,
                id_grupo: groupId // Enviar ID Grupo
            })
        })
        .then(response => response.json())
        .then(data => {
            document.querySelectorAll('.asistencia-check').forEach(chk => chk.checked = false);
            data.forEach(item => {
                let row = document.querySelector(`tr[data-id-alumno="${item.id_alumno}"]`);
                if (row) {
                    // Nota: item.fecha_clase es la columna nueva
                    let colIndex = currentColumnDates.indexOf(item.fecha_clase);
                    if (colIndex !== -1) {
                        let checkbox = row.querySelector(`.checkbox-cell[data-col-index="${colIndex}"] input`);
                        // Tu DB guarda 1 o 0
                        if (checkbox && item.asistencia === 1) { 
                            checkbox.checked = true;
                        }
                    }
                }
            });
        });
    }

    // MODIFICACIÓN 2: En el evento 'change' del checkbox (Guardar)
    document.querySelector('tbody').addEventListener('change', function(e) {
        if (e.target.classList.contains('asistencia-check')) {
            const checkbox = e.target;
            const row = checkbox.closest('tr');
            const cell = checkbox.closest('td');
            
            const groupId = document.getElementById('current-group-id').value;
            const idAlumno = row.getAttribute('data-id-alumno');
            const colIndex = cell.getAttribute('data-col-index');
            const fecha = currentColumnDates[colIndex];
            
            fetch('/api/guardar_asistencia', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    id_alumno: idAlumno,
                    id_grupo: groupId, // Importante para tu DB
                    fecha: fecha,
                    asistio: checkbox.checked
                })
            });
        }
    });