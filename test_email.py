from dotenv import load_dotenv
load_dotenv()

from utils.email import invia_email
from utils.templates import email_benvenuto_contatto

risultato = invia_email(
    "tua-email@test.com",
    "Test",
    "Test email SB Food Consulting",
    email_benvenuto_contatto("Mario")
)
print("Inviata!" if risultato else "Errore")
