FROM python:3.12-slim

# Zależności systemowe: WeasyPrint (PDF) wymaga Pango/Cairo/GDK-Pixbuf w systemie
# (odpowiednik bólu z MSYS2+GTK3 na Windows — tu to zwykły apt-get).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libcairo2 \
    libffi-dev \
    libmagic1 \
    shared-mime-info \
    fonts-liberation \
    # DejaVu jest tu za symbole Unicode, ktorych Liberation nie ma (np. flaga U+2691
    # w naglowku protokolu trakowni). Bez tego WeasyPrint wstawia .notdef i psuje
    # mape ToUnicode calej linii — PDF wyglada zle i nie da sie z niego wyciagnac tekstu.
    fonts-dejavu-core \
    build-essential \
    python3-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# pytest to narzedzie dev (nie zaleznosc produkcyjna) - stad poza requirements.txt,
# ktore steruje deploymentem na produkcje.
RUN pip install --no-cache-dir pytest==9.0.3

COPY . .

EXPOSE 5000

CMD ["flask", "run", "--host=0.0.0.0", "--port=5000"]
