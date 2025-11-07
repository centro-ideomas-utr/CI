        document.getElementById('password-form').addEventListener('submit', function(e) {
            const newPass = document.getElementById('new_pass').value;
            const confirmPass = document.getElementById('confirm_pass').value;

            if (newPass !== confirmPass) {
                e.preventDefault(); 
                alert('La nueva contraseña y la confirmación no coinciden. Por favor, inténtalo de nuevo.');
            }
        });