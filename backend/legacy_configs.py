from typing import Dict, Any


CLIENT_CONFIGS: Dict[str, Dict[str, Any]] = {
    "cafe-minima": {
        "business_name": "Café Mínima",
        "system_prompt": "Eres el asistente virtual de Café Mínima en México. Eres amigable, respondes dudas sobre el menú, horarios y ubicación. Tu objetivo es ayudar y guiar al usuario para que comparta su nombre y teléfono de manera natural. Respuestas muy breves (máximo 3 líneas).",
        "phone": "+52 55 1234 5678",
        "hours": "8:00 AM - 6:00 PM",
        "address": "Roma Norte, CDMX",
        "avatar": "https://images.unsplash.com/photo-1550567433-89a8ed4b23fa?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjAxODF8MHwxfHNlYXJjaHwxfHxtb2Rlcm4lMjBtaW5pbWFsJTIwY2FmZSUyMHN0b3JlZnJvbnR8ZW58MHx8fHwxNzc0NTAyNTg0fDA&ixlib=rb-4.1.0&q=85",
        "image": "https://images.unsplash.com/photo-1752754331999-a20ee211ec20?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjAxODF8MHwxfHNlYXJjaHwyfHxtb2Rlcm4lMjBtaW5pbWFsJTIwY2FmZSUyMHN0b3JlZnJvbnR8ZW58MHx8fHwxNzc0NTAyNTg0fDA&ixlib=rb-4.1.0&q=85",
        "greeting": "¡Hola! Soy el asistente virtual de Café Mínima. ¿En qué te puedo ayudar hoy?"
    },
    "dentista-lopez": {
        "business_name": "Dentista López",
        "system_prompt": "Eres el recepcionista virtual del consultorio Dentista López en México. Eres profesional y empático. Ayudas a los pacientes a resolver dudas sobre servicios dentales y buscar agendar citas. Tu objetivo es obtener su nombre y teléfono para que el doctor los contacte. Respuestas muy breves (máximo 3 líneas).",
        "phone": "+52 55 9876 5432",
        "hours": "9:00 AM - 7:00 PM",
        "address": "Polanco, CDMX",
        "avatar": "https://images.unsplash.com/photo-1598256989800-fea5ce514169?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjAxODF8MHwxfHNlYXJjaHwzfHxkZW50aXN0fGVufDB8fHx8MTY4MzY0MzUzM3ww&ixlib=rb-4.1.0&q=85",
        "image": "https://images.unsplash.com/photo-1606811841689-23dfddce3e95?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjAxODF8MHwxfHNlYXJjaHwyfHxkZW50aXN0JTIwb2ZmaWNlfGVufDB8fHx8MTY4MzY0MzU0Mnww&ixlib=rb-4.1.0&q=85",
        "greeting": "¡Hola! Bienvenido al consultorio Dentista López. ¿En qué puedo ayudarte?"
    },
    "default": {
        "business_name": "Negocio Demo",
        "system_prompt": "Eres un asistente virtual profesional para un negocio local en México. Tu objetivo es ayudar a los clientes y guiarlos para que dejen su nombre y teléfono. Respuestas muy breves (máximo 3 líneas).",
        "phone": "+52 55 0000 0000",
        "hours": "Lunes a Viernes, 9AM - 5PM",
        "address": "Centro Histórico, CDMX",
        "avatar": "https://images.unsplash.com/photo-1497366216548-37526070297c?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjAxODF8MHwxfHNlYXJjaHwzfHxidXNpbmVzc3xlbnwwfHx8fDE2ODM2NDM1NTZ8MA&ixlib=rb-4.1.0&q=85",
        "image": "https://images.unsplash.com/photo-1497366216548-37526070297c?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjAxODF8MHwxfHNlYXJjaHwzfHxidXNpbmVzc3xlbnwwfHx8fDE2ODM2NDM1NTZ8MA&ixlib=rb-4.1.0&q=85",
        "greeting": "Hola, soy el asistente virtual de este negocio. ¿Cómo puedo ayudarte?"
    }
}


DEFAULT_SLUG = "default"
DEMO_SLUGS = {DEFAULT_SLUG}
