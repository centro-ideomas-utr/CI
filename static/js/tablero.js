document.addEventListener('DOMContentLoaded', function () {
    
    let calendarEl = document.getElementById('calendar');
    
    if (calendarEl) {
        let calendar = new FullCalendar.Calendar(calendarEl, {
            initialView: 'dayGridMonth',
            locale: 'es',
            headerToolbar: {
                left: 'prev,next today',
                center: 'title',
                right: 'dayGridMonth,timeGridWeek,timeGridDay'
            },
            events: CALENDAR_EVENTS,
            
            // Mostrar solo un punto
            eventDisplay: 'dot',

            // Tooltip al hacer hover
            eventDidMount: function(info) {
                info.el.title = info.event.title;
            },

            // (Opcional) Clic en el punto muestra alerta
            eventClick: function(info) {
                alert(info.event.title);
            }
        });
        calendar.render();
    }
});