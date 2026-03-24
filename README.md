# Moto Oportunidades 🏍️

Detecta publicaciones de motos de primeras marcas (Honda, Yamaha, Kawasaki, KTM, Ducati) que están **por debajo del precio de mercado** en MercadoLibre Argentina.

## Qué hace

- Busca publicaciones por marca en la categoría de motos de MLA
- Calcula la **mediana de precios** del mercado por marca usando todas las publicaciones disponibles
- Marca como oportunidad cualquier publicación que esté un porcentaje configurable por debajo de esa mediana
- Detecta **palabras clave de urgencia**: `urgente`, `liquido`, `oportunidad` y más
- **Filtra automáticamente anticipos y señas** (el precio analizado siempre es el precio final)
- Muestra un puntaje de oportunidad del 1 al 5 ★
- Exporta los resultados a CSV

## Instalación

```bash
# 1. Clonar el repositorio
git clone https://github.com/tu-usuario/moto-oportunidades.git
cd moto-oportunidades

# 2. Crear entorno virtual
python3 -m venv venv
source venv/bin/activate      # macOS/Linux
# venv\Scripts\activate       # Windows

# 3. Instalar dependencias
pip install -r requirements.txt

# Si pip está configurado con un índice privado (ej. entorno corporativo):
pip install -r requirements.txt -i https://pypi.org/simple/

# 4. Configurar entorno (opcional, para mayor rate limit)
cp .env.example .env
# Editá .env con tus credenciales de MercadoLibre si las tenés
```

## Uso

```bash
# Búsqueda completa con todas las marcas (default)
python main.py

# Solo algunas marcas
python main.py --brands Honda Yamaha

# Umbral del 15% en lugar del 20% default
python main.py --threshold 0.15

# Mostrar solo el top 15 resultados
python main.py --top 15

# Mostrar solo publicaciones con keywords de urgencia
python main.py --keywords-only

# Puntaje mínimo 3 estrellas
python main.py --min-score 3

# Sin exportar CSV
python main.py --no-export

# Combinado
python main.py --brands Honda KTM --threshold 0.18 --top 20 --min-score 2
```

## Puntaje de oportunidad ★

| Puntaje | Criterio |
|---------|----------|
| ★★★★★ | Precio ≥30% bajo mediana + keywords |
| ★★★★☆ | Precio ≥20% bajo mediana + keywords, o precio ≥30% bajo mediana |
| ★★★☆☆ | Precio ≥20% bajo mediana |
| ★★☆☆☆ | Solo keywords de urgencia |
| ★☆☆☆☆ | Un solo indicador débil |

## Cómo funciona el análisis de precio

1. Para cada marca se descargan hasta 200 publicaciones de MercadoLibre
2. Se filtran anticipos, señas y precios irrealmente bajos
3. Se calcula la **mediana** de precios como referencia de mercado
4. Una publicación se considera "bajo mercado" si su precio está más de un X% por debajo de esa mediana (default 20%)
5. El análisis siempre usa el precio final publicado, nunca anticipos

## Variables de entorno

Ver `.env.example` para la lista completa. Las credenciales de MercadoLibre son opcionales pero permiten mayor rate limit.

## Requisitos

- Python 3.10+
- Ver `requirements.txt`
