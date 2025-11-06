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
            // NOTA: En archivos .js estáticos NO se puede usar {{ url_for(...) }}. 
            // Se debe usar la URL directa o definirla como variable global en Jinja. 
            // Asumimos que la URL directa es '/guardar-personal'.
            fetch("/guardar-personal", { 
                method: 'POST',
                body: formData,
            })
            .then(response => {
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
                    location.reload(); // Recargar la página para actualizar la lista
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
    
    // ==========================================================
    // 5. FUNCIÓN DE ELIMINACIÓN (Dar de Baja)
    // Se adjunta al objeto global window para que sea accesible desde onclick en HTML.
    // ==========================================================
    window.confirmDelete = function(tipo, id, nombre) {
        if (!confirm(`¿Está seguro de dar de baja a ${nombre} (${tipo})? Esta acción es irreversible y eliminará todos sus datos asociados.`)) {
            return;
        }

        // Llamada AJAX a la ruta de eliminación en Flask: /eliminar-personal/<tipo>/<id>
        fetch(`/eliminar-personal/${tipo}/${id}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            }
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(errorData => {
                    throw new Error(errorData.message || 'Error al intentar eliminar.');
                });
            }
            return response.json();
        })
        .then(data => {
            alert(data.message);
            if (data.status === 'success') {
                location.reload(); // Recargar la lista
            }
        })
        .catch(error => {
            console.error('Error al eliminar:', error);
            alert('Error al eliminar personal: ' + error.message);
        });
    };
});