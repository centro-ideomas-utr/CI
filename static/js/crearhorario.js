    // --- Lógica del Menú Lateral (Sidebar) ---
document.addEventListener('DOMContentLoaded', function() {
    const menuIcon = document.getElementById('menu-icon');
    const sidebar = document.getElementById('sidebar');
    const pageContent = document.getElementById('page-content');

    // Verificar que los elementos existan
    if (menuIcon && sidebar && pageContent) {
        menuIcon.addEventListener('click', () => {
            // 1. Mostrar u ocultar el sidebar
            sidebar.classList.toggle('active');

            // 2. Empujar el contenido (Solo si es pantalla grande)
            if (sidebar.classList.contains('active')) {
                // Si es escritorio (mayor a 768px), empujamos el contenido
                if (window.innerWidth > 768) {
                    pageContent.style.marginLeft = '230px';
                }
            } else {
                // Si se cierra, regresamos el margen a 0
                pageContent.style.marginLeft = '0';
            }
        });
    }
});
    let sedes = JSON.parse('{{ sedes | tojson }}');
    
    // Lista global que contendrá los horarios cargados por AJAX (desde /api/horarios_base)
    let HORARIOS_BASE = [];

    let selectedSede = sedes.length > 0 ? sedes[0] : '';
    
    // El 'timeSlots' define las etiquetas de las filas en la cuadrícula
    const timeSlots = ['08:00', '08:30', '09:00', '09:30', '10:00', '10:30','11:00', '11:30', '12:00', '12:30', '13:00', '13:30','14:00', '14:30', '15:00','15:30', '16:00', '16:30', '17:00', '17:30', '18:00','18:30','19:00','19:30','20:00','20:30']; 
    const dayNames = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb'];
    
    // Mapeo inverso de nombres de días a números (para actualizar HORARIOS_BASE)
    const dayNamesToNum = {'Lun': 1, 'Mar': 2, 'Mié': 3, 'Jue': 4, 'Vie': 5, 'Sáb': 6};


    // --- UI/STATE FUNCTIONS ---

    function showMessage(text, isError = false) {
        document.getElementById('modal-text').textContent = text;
        const confirmBtn = document.querySelector('#message-modal button');
        
        if (isError) {
             confirmBtn.classList.remove('bg-blue-600', 'hover:bg-blue-700');
             confirmBtn.classList.add('bg-red-600', 'hover:bg-red-700');
        } else {
             confirmBtn.classList.remove('bg-red-600', 'hover:bg-red-700');
             confirmBtn.classList.add('bg-blue-600', 'hover:bg-blue-700');
        }

        document.getElementById('message-modal').classList.remove('hidden'); 
    }

    function toggleMenu() {
        const sidebar = document.getElementById('sidebar');
        const pageContent = document.getElementById('page-content');
        const isActive = sidebar.classList.toggle('active');

        // Ajuste de margen para desktop si el sidebar está abierto
        if (window.innerWidth > 1000) {
            pageContent.classList.toggle('shifted', isActive);
        }
    }

   function renderSedes() {
    const container = document.getElementById('sedes-container');
    
    // Limpiamos solo los wrappers de sedes existentes, manteniendo el botón de "Añadir"
    container.querySelectorAll('.sede-wrapper').forEach(e => e.remove());
    
    const addButton = container.querySelector('.add-sede-btn');

    sedes.forEach(sede => {
        // 1. Crear el contenedor (wrapper)
        const wrapper = document.createElement('div');
        wrapper.className = 'sede-wrapper';

        // 2. Crear el botón principal de la Sede
        const btn = document.createElement('button');
        btn.className = `sede-btn ${sede === selectedSede ? 'active' : ''}`;
        btn.innerHTML = `<i class="fas fa-map-marker-alt"></i> ${sede}`;
        btn.onclick = () => selectSede(sede);

        // 3. Crear el botón de Eliminar (X)
        const delBtn = document.createElement('button');
        delBtn.className = 'delete-sede-btn';
        delBtn.innerHTML = '<i class="fas fa-times"></i>';
        delBtn.title = "Eliminar Sede";
        
        // Evento para eliminar
        delBtn.onclick = (e) => {
            e.stopPropagation(); // Evita que se seleccione la sede al hacer clic en eliminar
            deleteSede(sede);
        };

        // 4. Unir todo
        wrapper.appendChild(btn);
        wrapper.appendChild(delBtn);
        container.insertBefore(wrapper, addButton);
    });
}
async function deleteSede(sedeName) {
    // 1. Confirmación de seguridad
    if (!confirm(`¿Estás seguro de eliminar la sede "${sedeName}"? Se eliminarán todos los horarios asociados.`)) {
        return;
    }

    try {
        // 2. Llamada al Backend (Flask)
        // Asumiendo que crearás una ruta en Python: @app.route('/eliminar_sede', methods=['POST'])
        const res = await fetch('/eliminar_sede', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sede: sedeName })
        });

        const data = await res.json();

        if (res.ok) {
            // 3. Éxito: Actualizar interfaz
            showMessage("Eliminado", `Sede ${sedeName} eliminada correctamente.`, "success");

            // Remover de la lista local
            sedes = sedes.filter(s => s !== sedeName);
            
            // Limpiar horarios locales de esa sede
            HORARIOS_BASE = HORARIOS_BASE.filter(h => h.sede !== sedeName);

            // Si eliminamos la sede que estábamos viendo, cambiar a otra o limpiar
            if (selectedSede === sedeName) {
                selectedSede = sedes.length > 0 ? sedes[0] : '';
                if (selectedSede) {
                    selectSede(selectedSede);
                } else {
                    // No quedan sedes
                    document.getElementById('panel-title').textContent = "Sin Sedes";
                    document.getElementById('current-sede-name').textContent = "...";
                    document.getElementById('timetable').innerHTML = '<p class="text-center py-10">No hay sedes registradas.</p>';
                    renderSedes();
                }
            } else {
                // Solo renderizar botones si no cambió la vista actual
                renderSedes();
            }

        } else {
            showMessage("Error", data.message || "No se pudo eliminar la sede.", "error");
        }

    } catch (error) {
        console.error(error);
        // Fallback visual si no hay backend conectado aún:
        // (Si solo quieres probar la interfaz visual, descomenta las líneas de abajo y comenta el fetch)
        /*
        sedes = sedes.filter(s => s !== sedeName);
        renderSedes();
        showMessage("Atención", "Sede eliminada solo visualmente (error de conexión).", "error");
        */
       showMessage("Error", "Error de conexión con el servidor.", "error");
    }
}

    function selectSede(sedeName) {
        selectedSede = sedeName;
        
        // Activar la transición del workspace
        document.getElementById('workspace-container').classList.add('active');

        document.getElementById('panel-title').textContent = `Crear Franja Horaria en Campus ${sedeName}`;
        document.getElementById('current-sede-name').textContent = `${sedeName}`;
        document.getElementById('sede_input_hidden').value = sedeName; // Actualizar el campo oculto
        
        renderSedes(); // Re-renderizar para actualizar el botón activo
        populateTimetable();
    }
    
    function addSede() {
        const newSedeName = prompt("Introduce el nombre de la nueva Sede (ej: Sur):"); 
        if (newSedeName && newSedeName.trim() !== '') {
            const cleanName = newSedeName.trim();
            if (sedes.includes(cleanName)) {
                showMessage(`La Sede "${cleanName}" ya existe.`, true);
                return;
            }
            // Simulación de la adición de la sede
            sedes.push(cleanName);
            renderSedes();
            selectSede(cleanName); // Seleccionar la nueva sede
            showMessage(`Sede "${cleanName}" añadida correctamente.`);
        } else if (newSedeName) {
            showMessage("El nombre de la Sede no es válido.", true);
        }
    }

    function deleteSede(sedeName) {
        if (sedes.length <= 1) {
            showMessage("No puedes eliminar la única sede restante.", true);
            return;
        }

        if (confirm(`¿Estás seguro de que quieres eliminar la sede "${sedeName}"? Esto eliminará todos los horarios base asociados.`)) {
            const index = sedes.indexOf(sedeName);
            if (index > -1) {
                sedes.splice(index, 1);
                
                // Si la sede eliminada era la seleccionada, selecciona la primera disponible
                if (selectedSede === sedeName) {
                    selectedSede = sedes[0];
                }
                
                // Simulación: eliminar horarios asociados
                HORARIOS_BASE = HORARIOS_BASE.filter(item => item.sede !== sedeName);

                renderSedes();
                selectSede(selectedSede);
                showMessage(`Sede "${sedeName}" eliminada correctamente.`);
            }
        }
    }

    // --- TIMETABLE LOGIC (Muestra las franjas horarias base creadas) ---

    function populateTimetable() {
        const timetable = document.getElementById('timetable');
        timetable.innerHTML = ''; // Limpiar contenido existente

        // 1. Añadir encabezados
        timetable.innerHTML += `<div class="time-header">Hora</div>`;
        dayNames.forEach(day => {
            timetable.innerHTML += `<div class="day-header">${day}</div>`;
        });

        // 2. Añadir slots de tiempo y celdas
        timeSlots.forEach((timeSlot, timeIndex) => {
            timetable.innerHTML += `<div class="time-slot">${timeSlot}</div>`; // Etiqueta de la hora

            // Celdas de los días (1=Lun hasta 6=Sáb)
            for (let day = 1; day <= 6; day++) {
                const cell = document.createElement('div');
                cell.className = 'time-slot';
                
                const uniqueHorarioIds = new Set(); // Para evitar duplicados en la celda

                // Buscar todos los *slots de tiempo base* para este día y hora en la sede seleccionada
                const assignments = HORARIOS_BASE.filter(item => 
                    item.sede === selectedSede &&
                    item.day === day &&
                    item.time === timeSlot
                );

                if (assignments.length > 0) {
                    // Poblar celda con los slots de tiempo base
                    assignments.forEach(assignment => {
                        // Solo procesar si el ID es nuevo en esta celda
                        if (!uniqueHorarioIds.has(assignment.id)) {
                            uniqueHorarioIds.add(assignment.id);

                            const slot = document.createElement('div');
                            slot.className = 'slot-occupied';
                            slot.setAttribute('data-id', assignment.id);
                            
                            // *** ASIGNACIÓN DEL EVENTO DE CLIC ***
                            slot.onclick = () => openEditModal(assignment.id);

                            // Tooltip solo con el rango de horas
                            slot.title = `Franja Horaria Base: ${assignment.time} - ${assignment.end_time}`;
                            slot.innerHTML = `
                                <strong>Disponible</strong>
                                <span>${assignment.time} - ${assignment.end_time}</span>
                                <small>ID: ${assignment.id}</small>
                            `;
                            cell.appendChild(slot);
                        }
                    });
                }

                timetable.appendChild(cell);
            }
        });
        
        // Si no hay horarios base, mostrar un mensaje claro
        if (HORARIOS_BASE.filter(item => item.sede === selectedSede).length === 0) {
            timetable.innerHTML = `<p class="text-center text-gray-500 py-10" style="grid-column: 1 / -1;">Aún no hay franjas horarias base registradas para ${selectedSede}.</p>`;
        }
    }

    // --- DATA FETCHING (Carga de datos inicial) ---

    async function fetchHorariosData() {
        try {
            const response = await fetch('/api/horarios_base');
            if (response.ok) {
                HORARIOS_BASE = await response.json();
                
                // Recalcular sedes si la lista inicial de Jinja estaba vacía
                if (sedes.length === 0 && HORARIOS_BASE.length > 0) {
                     sedes = [...new Set(HORARIOS_BASE.map(h => h.sede))];
                     selectedSede = sedes[0];
                }
            } else {
                showMessage("Error al cargar los horarios base desde el servidor.", true);
            }
        } catch (error) {
            console.error('Error fetching horarios:', error);
            showMessage('Error de red al conectar con el servidor de horarios.', true);
        }
    }
    
    // --- EDICIÓN Y ELIMINACIÓN DE HORARIOS ---

    async function openEditModal(id_horario) {
        try {
            // Cargar detalle del horario
            const response = await fetch(`/api/horario_detail/${id_horario}`);
            if (!response.ok) {
                const error = await response.json();
                showMessage(`Error al cargar datos: ${error.message}`, true);
                return;
            }
            const data = await response.json();

            // 1. Rellenar el modal
            document.getElementById('edit-id-horario').value = data.id_horario;
            document.getElementById('edit-id-display').textContent = data.id_horario;
            document.getElementById('edit_hora_inicio').value = data.hora_inicio;
            document.getElementById('edit_hora_fin').value = data.hora_fin;

            // 2. Rellenar las sedes en el select
            const sedeSelect = document.getElementById('edit_sede');
            sedeSelect.innerHTML = '';
            // Asegurar que todas las sedes actuales estén disponibles
            sedes.forEach(sede => {
                 const option = document.createElement('option');
                 option.value = sede;
                 option.textContent = sede;
                 if (sede === data.sede) {
                     option.selected = true;
                 }
                 sedeSelect.appendChild(option);
            });


            // 3. Rellenar los checkboxes de días
            const checkboxes = document.querySelectorAll('#edit-days-checkbox-group input[type="checkbox"]');
            checkboxes.forEach(checkbox => {
                 // El campo 'data.dias' es una lista de strings de días (e.g., ['Lun', 'Mié'])
                 checkbox.checked = data.dias.includes(checkbox.value);
            });

            // 4. Mostrar el modal
            document.getElementById('edit-modal').classList.remove('hidden');

        } catch (error) {
            console.error('Error al abrir modal de edición:', error);
            showMessage('Error de conexión o datos al cargar el horario.', true);
        }
    }

    async function deleteHorario() {
        const id_horario = document.getElementById('edit-id-horario').value;
        
        // Usamos confirm() para la simplicidad del demo, aunque un modal es mejor.
        if (!confirm(`¿Confirmas que deseas eliminar permanentemente el Horario ID ${id_horario}? Si está asignado a un curso, la operación fallará.`)) {
            return;
        }

        try {
            const response = await fetch(`/eliminar_horario_base/${id_horario}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                }
            });
            const result = await response.json();

            if (response.ok) {
                showMessage(result.message);
                
                // Actualizar la lista global: eliminar todas las entradas con ese ID
                HORARIOS_BASE = HORARIOS_BASE.filter(h => h.id !== parseInt(id_horario));

                document.getElementById('edit-modal').classList.add('hidden');
                populateTimetable(); // Recargar la cuadrícula
                
            } else {
                showMessage(`Error al eliminar: ${result.message}`, true);
            }
        } catch (error) {
            console.error('Error de red al eliminar:', error);
            showMessage('Error de conexión con el servidor. Intente más tarde.', true);
        }
    }

    // --- FORM SUBMISSION (Registrar Nuevo Horario) ---

    document.getElementById('assign-form').addEventListener('submit', async function(event) {
        event.preventDefault();

        const form = event.target;
        const formData = new FormData(form);
        
        const horaInicio = formData.get('hora_inicio');
        
        if (!timeSlots.includes(horaInicio)) {
             showMessage(`La hora de inicio (${horaInicio}) debe ser una de las horas de la cuadrícula (${timeSlots.join(', ')}).`, true);
             return;
        }

        try {
            const response = await fetch(form.action, {
                method: 'POST',
                body: formData 
            });

            const result = await response.json();

            if (response.ok) {
                showMessage(result.message);
                
                // Actualizar la lista de horarios local con el nuevo registro
                const dayMap = {1: 'Lun', 2: 'Mar', 3: 'Mié', 4: 'Jue', 5: 'Vie', 6: 'Sáb'};
                const selectedDays = formData.getAll('dias[]');
                
                selectedDays.forEach(dayId => {
                    HORARIOS_BASE.push({
                        id: result.id_horario,
                        sede: result.sede,
                        day: parseInt(dayId),
                        time: result.hora.split(' - ')[0],
                        end_time: result.hora.split(' - ')[1],
                        dias_str: dayMap[parseInt(dayId)]
                    });
                });
                
                // Si se añadió una sede nueva, recargar las sedes
                if (!sedes.includes(result.sede)) {
                    sedes.push(result.sede);
                }

                // Limpiar el formulario y recargar la visualización
                form.reset();
                selectSede(result.sede); // Selecciona la sede donde se guardó
                
            } else {
                showMessage(`Error al registrar: ${result.message}`, true);
            }
        } catch (error) {
            console.error('Error de red o servidor:', error);
            showMessage('Error de conexión con el servidor. Intente más tarde.', true);
        }
    });

    // --- FORM SUBMISSION (Guardar Edición) ---
    document.getElementById('edit-form').addEventListener('submit', async function(event) {
        event.preventDefault();

        const id_horario = document.getElementById('edit-id-horario').value;
        const sede = document.getElementById('edit_sede').value;
        const hora_inicio = document.getElementById('edit_hora_inicio').value;
        const hora_fin = document.getElementById('edit_hora_fin').value;
        
        const selectedDaysCheckboxes = document.querySelectorAll('#edit-days-checkbox-group input[type="checkbox"]:checked');
        const selectedDays = Array.from(selectedDaysCheckboxes).map(cb => cb.value); // ['Lun', 'Mar', ...]
        
        if (selectedDays.length === 0) {
            showMessage("Debe seleccionar al menos un día para el horario.", true);
            return;
        }

        if (!timeSlots.includes(hora_inicio)) {
             showMessage(`La hora de inicio (${hora_inicio}) debe ser una de las horas de la cuadrícula (${timeSlots.join(', ')}).`, true);
             return;
        }
        
        const payload = {
            id_horario: parseInt(id_horario),
            sede: sede,
            dias: selectedDays,
            hora_inicio: hora_inicio,
            hora_fin: hora_fin
        };

        try {
            const response = await fetch('/editar_horario_base', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const result = await response.json();

            if (response.ok) {
                showMessage(result.message);
                
                // 1. Eliminar entradas antiguas del ID en la lista global
                HORARIOS_BASE = HORARIOS_BASE.filter(h => h.id !== parseInt(id_horario));

                // 2. Añadir nuevas entradas actualizadas (una por cada día)
                const hora_start = result.hora.split(' - ')[0];
                const hora_end = result.hora.split(' - ')[1];
                
                selectedDays.forEach(dayStr => {
                    HORARIOS_BASE.push({
                        id: result.id_horario,
                        sede: result.sede,
                        day: dayNamesToNum[dayStr], // Convertir nombre a número para el render
                        time: hora_start,
                        end_time: hora_end,
                        dias_str: result.dias 
                    });
                });
                
                document.getElementById('edit-modal').classList.add('hidden');
                selectSede(result.sede); // Recargar la sede para ver el cambio
                
            } else {
                showMessage(`Error al guardar: ${result.message}`, true);
            }
        } catch (error) {
            console.error('Error de red al guardar edición:', error);
            showMessage('Error de conexión con el servidor. Intente más tarde.', true);
        }
    });


    // --- INITIALIZATION ---
    window.onload = async function() {
        // 1. Cargar datos desde la DB
        await fetchHorariosData();

        // 2. Inicializar la UI
        if (selectedSede) {
             document.getElementById('panel-title').textContent = `Crear Franja Horaria en Campus ${selectedSede}`;
             document.getElementById('sede_input_hidden').value = selectedSede;
             renderSedes();
             selectSede(selectedSede); 
        } else {
             // Estado vacío
             document.getElementById('current-sede-name').textContent = 'N/A';
             document.getElementById('workspace-container').classList.add('active');
             renderSedes(); // Renderiza solo el botón Añadir Sede
             document.getElementById('timetable').innerHTML = `<p class="text-center text-gray-500 py-10" style="grid-column: 1 / -1;">No hay sedes o franjas horarias base registradas.</p>`;
        }
        
        // Activar el workspace para la transición de entrada
        document.getElementById('workspace-container').classList.add('active');
    };
