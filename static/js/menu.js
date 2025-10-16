document.addEventListener('DOMContentLoaded', function() {
    // Selecciona el ícono del menú por su ID
    const menuIcon = document.getElementById('menu-icon');
    
    // Selecciona el menú lateral (sidebar) por su ID
    const sidebar = document.getElementById('sidebar');

    // Selecciona el contenido principal
    const pageContent = document.querySelector('.page-content');

    // Verifica que los elementos existan antes de agregar el evento
    if (menuIcon && sidebar) {
        menuIcon.addEventListener('click', () => {
            // Agrega o quita la clase 'active' del sidebar para mostrarlo u ocultarlo
            sidebar.classList.toggle('active');
            
            // Opcional: Empuja el contenido principal cuando el menú se abre
            if (sidebar.classList.contains('active')) {
                pageContent.style.marginLeft = '230px';
            } else {
                pageContent.style.marginLeft = '0';
            }
        });
    }
});