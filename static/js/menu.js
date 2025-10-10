// Espera a que todo el HTML se cargue antes de ejecutar el script
document.addEventListener("DOMContentLoaded", function() {

    // 1. Encontrar los elementos necesarios en el HTML
    const menuIcon = document.querySelector(".menu-icon");
    const sidebar = document.getElementById("sidebar");

    // 2. Definir la función que muestra u oculta el sidebar
    function toggleMenu() {
        // Añade o quita la clase 'active' al sidebar
        sidebar.classList.toggle("active");
    }

    // 3. Agregar un "escuchador" de clics al ícono de menú
    // Cuando se haga clic en menuIcon, se ejecutará la función toggleMenu
    menuIcon.addEventListener("click", toggleMenu);

});