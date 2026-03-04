import time
import sys
import os
sys.path.insert(0, '.')

print('START')

t0 = time.perf_counter()
from tools_calendar import ottieni_eventi_precaricati, aggiungi_evento_calendario
print(f'import calendar: {time.perf_counter()-t0:.3f}s')

t0 = time.perf_counter()
from tools_routine import imposta_sveglia
print(f'import routine: {time.perf_counter()-t0:.3f}s')

t0 = time.perf_counter()
import dateparser
print(f'import dateparser: {time.perf_counter()-t0:.3f}s')

t0 = time.perf_counter()
d = dateparser.parse('tra 5 minuti', languages=['it'], settings={'PREFER_DATES_FROM': 'future'})
print(f'dateparser.parse: {time.perf_counter()-t0:.3f}s -> {d}')

t0 = time.perf_counter()
r = aggiungi_evento_calendario.invoke({
    'sommario': 'Test dall\'IA',
    'data_ora_inizio': '2026-12-31 alle 10:00',
    'durata_minuti': 60
})
print(f'aggiungi evento: {time.perf_counter()-t0:.3f}s -> {r}')

t0 = time.perf_counter()
r2 = imposta_sveglia.invoke({'orario':'tra 60 minuti','messaggio':'test'})
print(f'imposta sveglia: {time.perf_counter()-t0:.3f}s -> {r2}')

print('DONE')
