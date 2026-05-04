from dotenv import load_dotenv
load_dotenv()

from utils.email import invia_email
from utils.templates import email_benvenuto_contatto

risultato = invia_email(
    "info@stefanodemartis.com",
    "Simone",
    "Test email SB Food Consulting",
    email_benvenuto_contatto("Simone")
)
print("Email inviata con successo!" if risultato else "Errore nell'invio")
