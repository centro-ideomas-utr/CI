document.addEventListener('DOMContentLoaded', function() {
    // --- Inicialización de Grupo ---
    const groupSelect = document.getElementById('group-select');
    // Si el select tiene un valor al cargar, úsalo; si no, null.
    let currentIdGrupo = groupSelect.value ? parseInt(groupSelect.value) : null;
    let currentIdAlumno = null;
    
    // --- Elementos del DOM ---
    const menuIcon = document.getElementById('menu-icon');
    const sidebar = document.getElementById('sidebar');
    const pageContent = document.querySelector('.page-content');
    const modal = document.getElementById('observation-modal');
    const modalContent = modal.querySelector('.modal-content');
    const closeModal = modal.querySelector('.close-btn');
    const modalTitle = document.getElementById('modal-title');
    const historyList = document.getElementById('history-list');
    const newObservationText = document.getElementById('new-observation-text');
    const saveButton = document.getElementById('save-observation-btn');
    const tableBody = document.querySelector('.table-container tbody');
    const printButton = document.getElementById('print-btn');

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

    // --- FUNCIONES AJAX ---
    async function fetchData(url, method = 'GET', data = null) {
        try {
            const options = {
                method: method,
                headers: {
                    'Content-Type': 'application/json',
                },
            };
            if (data) {
                options.body = JSON.stringify(data);
            }

            const response = await fetch(url, options);
            const result = await response.json();
            
            if (response.ok) { // Verifica status 200-299
                return result;
            } else {
                throw new Error(result.message || 'Error en la petición.');
            }
        } catch (error) {
            console.error('Error en fetchData:', error);
            alert('Error: ' + error.message);
            return { status: 'error', message: error.message };
        }
    }
    
    // --- FUNCIONES DE ASISTENCIA ---

    // Función para dibujar la tabla de alumnos
    function drawTable(alumnos) {
        tableBody.innerHTML = '';
        if (alumnos.length === 0) {
            tableBody.innerHTML = '<tr><td colspan="9" style="text-align: center;">No hay alumnos en este grupo.</td></tr>';
            return;
        }

        alumnos.forEach((alumno, index) => {
            // Simulación de asistencia (la primera columna es la clase "actual")
            const asistencia_simulada = ["P", "F", "P", "F"]; 
            const ultima_clase_status = asistencia_simulada[0];
            
            const rowHtml = `
                <tr data-id-alumno="${alumno.id_alumno}">
                    <td>${index + 1}</td>
                    <td>${alumno.matricula}</td>
                    <td class="alumno-nombre">${alumno.nombre_completo}</td>
                    <td style="text-align: center; white-space: nowrap;">
                        <button class="btn-obs ver-obs" data-id-alumno="${alumno.id_alumno}">Ver</button>
                        <button class="btn-obs anadir-obs" data-id-alumno="${alumno.id_alumno}">Añadir</button>
                    </td>
                    <td class="asistencia-dia" data-status="${ultima_clase_status}" data-clase="1">${ultima_clase_status}</td>
                    <td class="asistencia-dia" data-status="${asistencia_simulada[1]}" data-clase="2">${asistencia_simulada[1]}</td>
                    <td class="asistencia-dia" data-status="${asistencia_simulada[2]}" data-clase="3">${asistencia_simulada[2]}</td>
                    <td class="asistencia-dia" data-status="${asistencia_simulada[3]}" data-clase="4">${asistencia_simulada[3]}</td>
                    <td class="abs-count">${alumno.faltas}</td>
                </tr>
            `;
            tableBody.insertAdjacentHTML('beforeend', rowHtml);
        });
    }
    
    // Evento cambio de grupo
    groupSelect.addEventListener('change', function() {
        currentIdGrupo = parseInt(this.value);
        if (currentIdGrupo) {
            loadStudents(currentIdGrupo);
        } else {
            tableBody.innerHTML = '<tr><td colspan="9" style="text-align: center;">Selecciona un grupo válido.</td></tr>';
        }
    });
    
    // Cargar alumnos desde el backend
    async function loadStudents(idGrupo) {
        if (!idGrupo) return;
        tableBody.innerHTML = '<tr><td colspan="9" style="text-align: center;">Cargando alumnos...</td></tr>';
        
        const url = `/obtener_alumnos_grupo/${idGrupo}`;
        const result = await fetchData(url);
        
        if (result.status === 'success') {
            drawTable(result.alumnos);
        } else {
            tableBody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: red;">Fallo al cargar alumnos: ${result.message}</td></tr>`;
        }
    }
    
    // Carga inicial
    if (currentIdGrupo) {
        loadStudents(currentIdGrupo);
    }

    // --- LÓGICA DE EVENTOS DE CLICKS (Delegación) ---
    document.addEventListener('click', function(event) {
        const target = event.target;
        
        // 1. Manejar botones de Observaciones
        if (target.classList.contains('ver-obs') || target.classList.contains('anadir-obs')) {
            const row = target.closest('tr');
            currentIdAlumno = row.getAttribute('data-id-alumno');
            const nombre = row.querySelector('.alumno-nombre').textContent;
            const isViewAction = target.classList.contains('ver-obs');

            if (!currentIdAlumno) return;

            modalTitle.textContent = `Observaciones de: ${nombre}`;

            modalContent.classList.remove('view-only', 'add-only');
            if (isViewAction) {
                modalContent.classList.add('view-only');
            } else {
                modalContent.classList.add('add-only');
                newObservationText.value = '';
            }

            loadHistory(currentIdAlumno);
            modal.style.display = 'block';
        }
        
        // 2. Manejar clics en celdas de Asistencia
        if (target.classList.contains('asistencia-dia')) {
            const row = target.closest('tr');
            const idAlumnoAsistencia = row.getAttribute('data-id-alumno');
            const currentStatus = target.getAttribute('data-status');
            
            // Solo editar la columna 1
            if (target.getAttribute('data-clase') === "1") { 
                const newStatus = currentStatus === 'P' ? 'F' : 'P';
                const esPresente = newStatus === 'P';

                target.setAttribute('data-status', newStatus);
                target.textContent = newStatus;

                saveAttendance(idAlumnoAsistencia, esPresente, row);
            }
        }
    });
    
    async function saveAttendance(idAlumno, esPresente, row) {
        if (!currentIdGrupo) { alert('Selecciona un grupo primero.'); return; }
        
        const data = {
            id_alumno: parseInt(idAlumno),
            id_grupo: currentIdGrupo,
            asistencia: esPresente
        };

        const result = await fetchData('/guardar_asistencia', 'POST', data);
        
        if (result.status === 'success') {
            // Recargar para actualizar contadores
            loadStudents(currentIdGrupo); 
            console.log(result.message);
        }
    }
    
    // --- FUNCIONES DE COMENTARIOS (Modal) ---
    
    function renderHistory(historial) {
        historyList.innerHTML = '';
        if (!historial || historial.length === 0) {
            historyList.innerHTML = '<p class="no-data-msg">No hay observaciones registradas aún.</p>';
            return;
        }

        historial.forEach(entry => {
            const div = document.createElement('div');
            div.className = 'observation-entry';
            div.innerHTML = `
                <p class="obs-text">${entry.descripcion}</p>
                <p class="obs-meta">Fecha: ${entry.fecha_registro} | Maestro: ${entry.maestro_nombre}</p>
            `;
            historyList.appendChild(div);
        });
    }
    
    async function loadHistory(idAlumno) {
        historyList.innerHTML = '<p class="no-data-msg">Cargando historial...</p>';
        const url = `/comentarios?id_alumno=${idAlumno}`;
        const result = await fetchData(url);

        if (result.status === 'success') {
            renderHistory(result.historial);
        } else {
            historyList.innerHTML = `<p class="no-data-msg" style="color: red;">Error al cargar historial: ${result.message}</p>`;
        }
    }

    saveButton.addEventListener('click', async function() {
        const newText = newObservationText.value.trim();
        if (newText.length === 0) {
            alert('Por favor, escribe un comentario para guardar.');
            return;
        }
        
        const data = {
            id_alumno: parseInt(currentIdAlumno),
            descripcion: newText
        };
        
        const result = await fetchData('/comentarios', 'POST', data);
        
        if (result.status === 'success') {
            alert('¡Comentario guardado con éxito!');
            newObservationText.value = '';
            loadHistory(currentIdAlumno);
            modalContent.classList.remove('add-only');
            modalContent.classList.add('view-only');
        }
    });

    // --- CIERRE MODAL E IMPRESIÓN ---
    closeModal.onclick = function() { modal.style.display = 'none'; }
    window.onclick = function(event) {
        if (event.target == modal) { modal.style.display = 'none'; }
    }

    printButton.addEventListener('click', function() {
        window.print();
    });
});