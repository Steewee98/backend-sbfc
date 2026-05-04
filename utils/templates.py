def email_benvenuto_contatto(nome):
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width">
    </head>
    <body style="margin:0;padding:0;background:#f5f2ee;
    font-family:Arial,sans-serif">

    <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center" style="padding:40px 20px">
    <table width="600" cellpadding="0" cellspacing="0"
    style="max-width:600px;width:100%">

    <!-- HEADER -->
    <tr><td style="background:#37393f;padding:32px 40px;
    text-align:center">
        <p style="color:#f5f2ee;font-size:11px;
        letter-spacing:3px;margin:0 0 8px;
        text-transform:uppercase">SB Food Consulting</p>
        <p style="color:rgba(255,255,255,0.5);font-size:12px;
        margin:0;font-style:italic">
        Dove la ristorazione diventa strategia</p>
    </td></tr>

    <!-- BODY -->
    <tr><td style="background:#ffffff;padding:48px 40px">
        <h2 style="font-family:Georgia,serif;color:#1a1a1a;
        font-size:24px;margin:0 0 24px">
        Grazie per averci contattato, {nome}.</h2>

        <p style="color:#5a5a5a;font-size:15px;line-height:1.8;
        margin:0 0 24px">
        Abbiamo ricevuto la tua richiesta e ti risponderemo
        personalmente entro 24 ore.</p>

        <p style="color:#5a5a5a;font-size:15px;line-height:1.8;
        margin:0 0 32px">
        Nel frattempo, se vuoi fissare subito una chiamata
        conoscitiva gratuita di 30 minuti con Simone Braghetta,
        puoi prenotare direttamente qui:</p>

        <table cellpadding="0" cellspacing="0"
        style="margin:0 auto 40px">
        <tr><td style="background:#c4622d;border-radius:4px">
            <a href="https://calendly.com/sbfoodconsulting-info/30min"
            style="display:block;padding:16px 32px;color:#ffffff;
            text-decoration:none;font-size:15px;font-weight:bold">
            Prenota la tua chiamata gratuita &rarr;</a>
        </td></tr></table>

        <hr style="border:none;border-top:1px solid #edeae5;
        margin:0 0 32px">

        <p style="color:#c4622d;font-size:11px;font-weight:bold;
        letter-spacing:2px;text-transform:uppercase;margin:0 0 12px">
        Scopri SB Food Academy</p>

        <p style="color:#5a5a5a;font-size:14px;line-height:1.8;
        margin:0 0 24px">
        Mentre aspetti, dai un'occhiata al nostro percorso
        formativo online &mdash; 5 moduli operativi costruiti su
        30 anni di lavoro nei ristoranti italiani.</p>

        <table cellpadding="0" cellspacing="0"
        style="margin:0 auto">
        <tr><td style="border:2px solid #37393f;border-radius:4px">
            <a href="https://www.sbfoodconsulting.com/academy.html"
            style="display:block;padding:14px 28px;color:#37393f;
            text-decoration:none;font-size:14px;font-weight:bold">
            Scopri il corso &rarr;</a>
        </td></tr></table>
    </td></tr>

    <!-- FOOTER -->
    <tr><td style="background:#37393f;padding:24px 40px;
    text-align:center">
        <p style="color:rgba(255,255,255,0.5);font-size:12px;
        margin:0 0 8px">SB Food Consulting &mdash; Roma, Italia</p>
        <p style="color:rgba(255,255,255,0.4);font-size:11px;
        margin:0">info@sbfoodconsulting.com</p>
        <p style="color:rgba(255,255,255,0.3);font-size:10px;
        margin:12px 0 0">Hai ricevuto questa email perch&eacute; hai
        compilato il form sul nostro sito.</p>
    </td></tr>

    </table>
    </td></tr></table>
    </body>
    </html>
    """


def email_benvenuto_academy(nome, email, moduli, password_temp=None):
    moduli_testo = ', '.join([f"Modulo {m}" for m in moduli])

    password_html = ""
    if password_temp:
        password_html = f"""
        <div style="background:#f5f2ee;border-left:3px solid #c4622d;
        padding:16px 20px;margin:24px 0">
            <p style="margin:0 0 8px;font-size:13px;color:#5a5a5a">
            Le tue credenziali di accesso:</p>
            <p style="margin:0;font-size:14px;color:#1a1a1a">
            <strong>Email:</strong> {email}<br>
            <strong>Password temporanea:</strong> {password_temp}</p>
        </div>"""

    return f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="UTF-8"></head>
    <body style="margin:0;padding:0;background:#f5f2ee;
    font-family:Arial,sans-serif">

    <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center" style="padding:40px 20px">
    <table width="600" cellpadding="0" cellspacing="0"
    style="max-width:600px;width:100%">

    <!-- HEADER -->
    <tr><td style="background:#37393f;padding:32px 40px;
    text-align:center">
        <p style="color:#f5f2ee;font-size:11px;
        letter-spacing:3px;margin:0 0 8px;
        text-transform:uppercase">SB Food Academy</p>
        <p style="color:rgba(255,255,255,0.5);font-size:12px;
        margin:0;font-style:italic">
        Il tuo percorso formativo &egrave; iniziato.</p>
    </td></tr>

    <!-- BODY -->
    <tr><td style="background:#ffffff;padding:48px 40px">
        <h2 style="font-family:Georgia,serif;color:#1a1a1a;
        font-size:24px;margin:0 0 8px">
        Benvenuto in SB Food Academy, {nome}.</h2>

        <p style="color:#c4622d;font-size:13px;font-weight:bold;
        letter-spacing:1px;margin:0 0 24px">
        Acquisto confermato &mdash; {moduli_testo}</p>

        <p style="color:#5a5a5a;font-size:15px;line-height:1.8;
        margin:0 0 24px">
        Hai accesso immediato ai tuoi contenuti.
        Accedi alla tua area personale e inizia subito.</p>

        {password_html}

        <table cellpadding="0" cellspacing="0"
        style="margin:0 auto 40px">
        <tr><td style="background:#c4622d;border-radius:4px">
            <a href="https://www.sbfoodconsulting.com/academy.html#area-studenti"
            style="display:block;padding:16px 32px;color:#ffffff;
            text-decoration:none;font-size:15px;font-weight:bold">
            Accedi al corso &rarr;</a>
        </td></tr></table>

        <hr style="border:none;border-top:1px solid #edeae5;
        margin:0 0 32px">

        <p style="color:#5a5a5a;font-size:14px;line-height:1.8;
        margin:0 0 8px">Hai domande o hai bisogno di supporto?</p>
        <p style="color:#5a5a5a;font-size:14px;margin:0">
        Rispondi a questa email o scrivici a
        <a href="mailto:info@sbfoodconsulting.com"
        style="color:#c4622d">info@sbfoodconsulting.com</a></p>
    </td></tr>

    <!-- FOOTER -->
    <tr><td style="background:#37393f;padding:24px 40px;
    text-align:center">
        <p style="color:rgba(255,255,255,0.5);font-size:12px;
        margin:0 0 8px">SB Food Consulting &mdash; Roma, Italia</p>
        <p style="color:rgba(255,255,255,0.4);font-size:11px;
        margin:0">info@sbfoodconsulting.com</p>
    </td></tr>

    </table>
    </td></tr></table>
    </body>
    </html>
    """
