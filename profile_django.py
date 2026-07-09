import os
import time
import django
from django.test import Client
from django.db import connection

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rental.settings')
django.setup()
client = Client()
for path in ['/items/', '/inventory/', '/']:
    connection.queries.clear()
    start = time.time()
    response = client.get(path)
    elapsed = time.time() - start
    print('PATH', path)
    print('STATUS', response.status_code)
    print('LEN', len(response.content))
    print('TIME', elapsed)
    print('QUERIES', len(connection.queries))
    for q in connection.queries:
        print('  TIME=' + q.get('time', '?') + ' SQL=' + q.get('sql', '')[:200])
    print('---')
