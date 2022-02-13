FROM python:latest


RUN git clone https://github.com/adenosinetp10/Akinator-Bot.git /Akinator
WORKDIR /Akinator
RUN python -m pip install --upgrade pip
RUN python -m pip install --no-cache-dir -r /Akinator/requirements.txt
CMD python3 __main__.py

