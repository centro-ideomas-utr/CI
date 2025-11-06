document.addEventListener('DOMContentLoaded', function () {
    
    // --- 1. LÓGICA PARA EL SIDEBAR (MENÚ) ---
    
    const menuIcon = document.getElementById('menu-icon');
    const sidebar = document.getElementById('sidebar');
    // Seleccionamos por clase, ya que en tu HTML no tiene ID
    const pageContent = document.querySelector('.page-content'); 

    // Nos aseguramos de que los elementos existan antes de añadir el evento
    if (menuIcon && sidebar && pageContent) {
        menuIcon.addEventListener('click', function() {
            
            // 1. Muestra u oculta el sidebar
            // (Tu CSS .sidebar.active lo pone en left: 0;)
            sidebar.classList.toggle('active');

            // 2. Mueve el contenido principal
            // (Tu CSS .page-content tiene la transición para margin-left)
            if (sidebar.classList.contains('active')) {
                // El ancho del sidebar es 230px según tu CSS
                pageContent.style.marginLeft = '230px';
            } else {
                // Vuelve a la normalidad
                pageContent.style.marginLeft = '0';
            }

            // 3. (Opcional) Anima el ícono de hamburguesa a una 'X'
            // Esto necesita que agregues estilos CSS para .menu-icon.active
            this.classList.toggle('active');
        });
    }

 let calendarEl = document.getElementById('calendar');
    
    // Solo intentar renderizar el calendario si existe en esta página
    if (calendarEl) {
        let calendar = new FullCalendar.Calendar(calendarEl, {
            initialView: 'dayGridMonth',
            locale: 'es',
            headerToolbar: {
                left: 'prev,next today',
                center: 'title',
                right: 'dayGridMonth,timeGridWeek,timeGridDay'
            },
            events: typeof CALENDAR_EVENTS !== 'undefined' ? CALENDAR_EVENTS : []
            
        });
        calendar.render();
    }
});