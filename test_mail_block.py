import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "JarvisLocale"))

from JarvisLocale.automations.tools_mail import fetch_mail_recenti, classifica_mail_con_llm
from JarvisLocale.logica_chat import llm

if __name__ == "__main__":
    print("Avvio test...")
    mail = fetch_mail_recenti(1)
    print("Fine test. Mail ottenute:", len(mail))
    if mail:
        print("Avvio test classifica_mail_con_llm...")
        classificate = classifica_mail_con_llm(mail, llm)
        print("Fine test classifica. Rilevanti:", len(classificate))
