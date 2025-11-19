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

        function addSede() {
            const name = prompt("Nombre de la nueva sede:");
            if (name) {
                const container = document.getElementById('sedes-container');
                const addButton = container.querySelector('.add-sede-btn');
                
                const wrapper = document.createElement('div');
                wrapper.className = 'sede-wrapper';
                wrapper.innerHTML = `
                    <button class="sede-btn" onclick="selectSede('${name}', this)">${name}</button>
                    <button class="delete-sede-btn" onclick="deleteSede(this)"><i class="fas fa-times"></i></button>
                `;
                
                container.insertBefore(wrapper, addButton);
            }
        }

        function deleteSede(btn) {
            if(confirm("¿Seguro que quieres eliminar esta sede?")) {
                btn.parentElement.remove();
                document.getElementById('workspace').classList.remove('active');
            }
        }

        function selectSede(name, btn) {
            document.querySelectorAll('.sede-btn').forEach(b => b.classList.remove('active'));
            if(btn) btn.classList.add('active');

            const ws = document.getElementById('workspace');
            ws.classList.add('active');
            document.getElementById('panel-title').innerText = "Asignar en " + name;
        }

        // --- Lógica para Asignar (MULTIPLE DÍAS) ---
        document.getElementById('assign-form').addEventListener('submit', function(e) {
            e.preventDefault();
            
            const salon = document.getElementById('salon').value;
            const idioma = document.getElementById('idioma').value;
            const maestro = document.getElementById('maestro').value;
            const hora = document.getElementById('hora').value;
            
            // Obtener días seleccionados
            const diasCheckboxes = document.querySelectorAll('input[name="dias"]:checked');
            
            if (diasCheckboxes.length === 0) {
                alert("Por favor selecciona al menos un día.");
                return;
            }
            
            if (!salon || !idioma || !maestro || !hora) {
                 alert("Por favor completa todos los campos.");
                 return;
            }

            // Iterar sobre cada día seleccionado
            diasCheckboxes.forEach(checkbox => {
                const dia = checkbox.value;
                const cellId = `cell-${dia}-${hora}`;
                const cell = document.getElementById(cellId);
                
                if(cell) {
                    const classCard = document.createElement('div');
                    classCard.className = 'slot-occupied';
                    classCard.innerHTML = `
                        <strong>${salon}</strong>
                        <span>${idioma}</span><br>
                        <small>${maestro}</small>
                    `;
                    
                    cell.appendChild(classCard);
                    
                    // Animación
                    classCard.style.animation = "highlight 0.5s ease";
                }
            });
        });
        
        const styleSheet = document.createElement("style");
        styleSheet.innerText = `
            @keyframes highlight {
                0% { background-color: #e8f4fc; }
                50% { background-color: #F7B801; }
                100% { background-color: #e8f4fc; }
            }
        `;
        document.head.appendChild(styleSheet);
