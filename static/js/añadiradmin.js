document.addEventListener('DOMContentLoaded', function() {
    
    // 1. SELECTORES PRINCIPALES
    const sidebar = document.getElementById('sidebar');
    const menuIcon = document.getElementById('menu-icon');
    
    const addPersonalBtn = document.getElementById('add-personal-btn');
    const modalOverlay = document.getElementById('add-personal-modal-overlay');
    const modalCloseBtn = document.getElementById('modal-close-btn');
    const personalForm = document.getElementById('add-personal-form');
    const saveButton = personalForm ? personalForm.querySelector('.btn-save') : null;
    const pageContent = document.querySelector('main'); 

    // ==========================================================
    // 2. LÓGICA DEL SIDEBAR (Menú Lateral y Animación)
    // ==========================================================
    if (menuIcon && sidebar && pageContent) {
        menuIcon.addEventListener('click', () => {
            sidebar.classList.toggle('active');
            // Animación: Empujar el contenido principal
            if (sidebar.classList.contains('active')) {
                pageContent.style.marginLeft = '230px'; 
            } else {
                pageContent.style.marginLeft = '0';
            }
        });
    }

    // ==========================================================
    // 3. LÓGICA DEL MODAL (Abrir/Cerrar)
    // ==========================================================
    if (addPersonalBtn && modalOverlay && modalCloseBtn && personalForm) {
        
        addPersonalBtn.addEventListener('click', function() {
            modalOverlay.style.display = 'flex';
        });

        modalCloseBtn.addEventListener('click', function() {
            modalOverlay.style.display = 'none';
            personalForm.reset();
        });

        modalOverlay.addEventListener('click', function(e) {
            if (e.target === modalOverlay) {
                modalOverlay.style.display = 'none';
                personalForm.reset();
            }
        });

        // ==========================================================
        // 4. LÓGICA DEL FORMULARIO (Envío AJAX con FormData)
        // ==========================================================

        personalForm.addEventListener('submit', function(e) {
            e.preventDefault(); 

            const formData = new FormData(personalForm);
            
            if (saveButton) {
                saveButton.disabled = true;
                saveButton.textContent = 'Guardando...';
            }
            
            // La ruta a tu función de Flask 'guardar_personal'
            fetch("{{ url_for('guardar_personal') }}", {
                method: 'POST',
                body: formData,
            })
            .then(response => {
                // Manejo de errores robusto: Verifica status 4xx/5xx
                if (!response.ok) {
                    return response.json().then(errorData => {
                        throw new Error(errorData.message || 'Error desconocido del servidor.');
                    });
                }
                return response.json();
            })
            .then(data => {
                alert('Éxito: ' + data.message); 
                if (data.status === 'success') {
                    modalOverlay.style.display = 'none'; 
                    personalForm.reset(); 
                    location.reload(); 
                }
            })
            .catch(error => {
                console.error('Fallo en el registro:', error);
                alert('Fallo en el registro: ' + error.message);
            })
            .finally(() => {
                if (saveButton) {
                    saveButton.disabled = false;
                    saveButton.textContent = 'Guardar Personal';
                }
            });
        });
    }
});