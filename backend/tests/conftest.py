import os

os.environ['DATABASE_URL'] = 'sqlite:///./test-nexus.db'
os.environ['STEP_DELAY'] = '0'
os.environ['OLLAMA_API_KEY'] = ''
os.environ['ELASTICSEARCH_URL'] = ''
os.environ['PAYPAL_CLIENT_ID'] = 'test-client'
os.environ['PAYPAL_CLIENT_SECRET'] = 'test-secret'
os.environ['PAYPAL_ENV'] = 'sandbox'
os.environ['SANDBOX_API_TOKEN'] = ''
