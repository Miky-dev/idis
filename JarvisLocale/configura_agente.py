import asyncio
from parlant.client import ParlantClient

async def main():
    # Connettiamoci al server locale di Parlant appena avviato
    client = ParlantClient(base_url="http://localhost:8080")
    
    print("1. Creazione dell'Agente JARVIS in corso...")
    # Creiamo l'identità base
    agent = await client.agents.create(
        name="JARVIS",
        description="Sei un assistente virtuale altamente efficiente, brillante e dal tono leggermente ironico, ispirato a J.A.R.V.I.S. Rispondi sempre in italiano."
    )
    print(f"✅ Agente creato! IL TUO AGENT ID È: {agent.id}")
    print("-" * 40)

    print("2. Iniezione delle Linee Guida (Guidelines)...")
    
    # Regola #1: La gestione dell'hardware (Arduino)
    await client.guidelines.create(
        agent_id=agent.id,
        condition="L'utente chiede di accendere o spegnere una luce, o nomina la parola LED.",
        action="Non dare spiegazioni lunghe o teoriche. Usa immediatamente lo strumento hardware associato per gestire il LED e conferma l'azione eseguita con una battuta breve e cortese."
    )

    # Regola #2: La ricerca in background
    await client.guidelines.create(
        agent_id=agent.id,
        condition="L'utente chiede di fare una ricerca accurata o profonda su un determinato argomento.",
        action="Non cercare di rispondere subito con i tuoi dati interni. Usa lo strumento di ricerca in background e avvisa l'utente che la ricerca richiederà del tempo e che il file verrà salvato sul desktop."
    )

    print("✅ Linee Guida configurate con successo dentro il cervello di Parlant!")
    print("\n⚠️ IMPORTANTE: Copia l'AGENT ID qui sopra, ci servirà nel file principale!")

if __name__ == "__main__":
    # Avviamo la funzione asincrona
    asyncio.run(main())