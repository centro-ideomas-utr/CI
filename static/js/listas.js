
        document.addEventListener('DOMContentLoaded', function() {
            // Elementos del DOM
            const modal = document.getElementById('observation-modal');
            const modalContent = modal.querySelector('.modal-content');
            const closeModal = modal.querySelector('.close-btn');
            const modalTitle = document.getElementById('modal-title');
            const historyList = document.getElementById('history-list');
            const newObservationText = document.getElementById('new-observation-text');
            const saveButton = document.getElementById('save-observation-btn');

            let currentMatricula = null;

            // --- Base de Datos Simulada (Reemplazar con tu backend) ---
            const simulatedObservations = {
                '2024-001': [
                    { text: "Requiere refuerzo en conjugación de verbos en pasado.", date: "15/Feb/2024", teacher: "Prof. Ana C." },
                    { text: "Excelente participación en la actividad de debate de hoy.", date: "05/Mar/2024", teacher: "Maestra B." }
                ],
                '2024-002': [
                    { text: "Estudiante ejemplar, siempre entrega las tareas a tiempo.", date: "20/Ene/2024", teacher: "Tutor Principal" }
                ],
                '2024-003': []
            };

            // Función para renderizar el historial en el modal
            function renderHistory(matricula) {
                historyList.innerHTML = '';
                const obs = simulatedObservations[matricula] || [];

                if (obs.length === 0) {
                    historyList.innerHTML = '<p class="no-data-msg">No hay observaciones registradas aún.</p>';
                    return;
                }

                obs.forEach(entry => {
                    const div = document.createElement('div');
                    div.className = 'observation-entry';
                    div.innerHTML = `
                        <p class="obs-text">${entry.text}</p>
                        <p class="obs-meta">Fecha: ${entry.date} | Maestro: ${entry.teacher}</p>
                    `;
                    historyList.appendChild(div);
                });
            }

            // --- Lógica de Apertura del Modal ---
            document.querySelectorAll('.ver-obs, .anadir-obs').forEach(button => {
                button.addEventListener('click', function() {
                    currentMatricula = this.getAttribute('data-matricula');
                    const row = this.closest('tr');
                    const nombre = row.querySelector('td:nth-child(3)').textContent;
                    const isViewAction = this.classList.contains('ver-obs');

                    modalTitle.textContent = `Observaciones de: ${nombre}`;

                    // Configurar el modal para la acción específica
                    modalContent.classList.remove('view-only', 'add-only');
                    if (isViewAction) {
                        modalContent.classList.add('view-only'); // Solo historial
                    } else {
                        modalContent.classList.add('add-only'); // Solo formulario
                        newObservationText.value = '';
                    }

                    renderHistory(currentMatricula);
                    modal.style.display = 'block';
                });
            });

            // --- Lógica de Cierre del Modal ---
            closeModal.onclick = function() { modal.style.display = 'none'; }
            window.onclick = function(event) {
                if (event.target == modal) { modal.style.display = 'none'; }
            }

            // --- Lógica para Guardar la Observación (Simulada) ---
            saveButton.addEventListener('click', function() {
                const newText = newObservationText.value.trim();
                if (newText.length === 0) {
                    alert('Por favor, escribe un comentario para guardar.');
                    return;
                }

                // SIMULACIÓN DE GUARDADO:
                const today = new Date().toLocaleDateString('es-ES', { day: '2-digit', month: 'short', year: 'numeric' }).replace('.', '');
                const newEntry = { text: newText, date: today, teacher: "Yo (Maestro Actual)" };

                if (!simulatedObservations[currentMatricula]) {
                    simulatedObservations[currentMatricula] = [];
                }
                simulatedObservations[currentMatricula].push(newEntry);
                
                alert('✅ ¡Comentario guardado con éxito!');
                
                // Mostrar el historial actualizado y el formulario vacío
                renderHistory(currentMatricula);
                modalContent.classList.remove('add-only');
                modalContent.classList.add('view-only');
                newObservationText.value = '';
            });

            // Funcionalidad para el botón Imprimir
            document.getElementById('print-btn').addEventListener('click', function() {
                window.print();
            });
        });
