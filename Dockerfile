FROM python:3


RUN git clone https://github.com/adenosinetp10/Akinator-Bot.git /root/Akinator/
WORKDIR /root/Akinator
RUN pip install --no-cache-dir -r /root/Akinator/requirements.txt
CMD [ "python", "__main__.py" ]

