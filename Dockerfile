FROM eclipse-temurin:17-jre-alpine AS dcm4che

# Download dcm4che toolkit
ENV DCM4CHE_VERSION=5.32.0
RUN apk add --no-cache curl unzip && \
    curl -L "https://sourceforge.net/projects/dcm4che/files/dcm4che3/${DCM4CHE_VERSION}/dcm4che-${DCM4CHE_VERSION}-bin.zip/download" \
    -o /tmp/dcm4che.zip && \
    unzip /tmp/dcm4che.zip -d /opt && \
    rm /tmp/dcm4che.zip && \
    ln -s /opt/dcm4che-${DCM4CHE_VERSION} /opt/dcm4che


FROM python:3.11-alpine

# Copy JRE from temurin image (much smaller than installing via apt)
COPY --from=dcm4che /opt/java/openjdk /opt/java/openjdk
ENV JAVA_HOME=/opt/java/openjdk
ENV PATH="${JAVA_HOME}/bin:${PATH}"

# Copy dcm4che toolkit
COPY --from=dcm4che /opt/dcm4che /opt/dcm4che
ENV PATH="/opt/dcm4che/bin:${PATH}"

# Setup application
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Create directories
RUN mkdir -p /tmp/dicom-uploads /app/logs

ENV UPLOAD_FOLDER=/tmp/dicom-uploads
ENV CSV_LOG_FILE=/app/logs/dicom_send_log.csv
ENV STORESCU_PATH=/opt/dcm4che/bin/storescu

EXPOSE 5000

CMD ["python", "app.py"]
