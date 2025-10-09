import logger from './logger';
const log = logger.child({ module: 'storage' });

export const loadLocalMqttData = () => {
    const pin = localStorage.getItem("pin");
    const mqtt_host = localStorage.getItem("mqtt_host");
    const mqtt_port = parseInt(localStorage.getItem("mqtt_port"));
    const mqtt_version = parseInt(localStorage.getItem("mqtt_version"));
    const mqtt_use_ssl = localStorage.getItem("mqtt_use_ssl") === "true";
    const mqtt_username = localStorage.getItem("mqtt_username");
    const mqtt_password = localStorage.getItem("mqtt_password");
    const date = parseInt(localStorage.getItem("date"));

    if (isNaN(pin) || isNaN(date)) {
        log.debug("No valid data found in local storage");
        return null;
    }

    if (Date.now() - date > 1000 * 60 * 20) {
        log.debug("Data found in local storage, but it's too old");
        return null;
    }

    const data = {
        pin: pin,
        mqtt_host: mqtt_host,
        mqtt_port: mqtt_port,
        mqtt_version: mqtt_version,
        mqtt_use_ssl: mqtt_use_ssl,
        mqtt_username: mqtt_username,
        mqtt_password: mqtt_password,
    };

    log.debug(`MQTT data ${JSON.stringify(data)} found in local storage`);

    return data;
};

export const saveLocalMqttData = (data) => {
    log.debug(`Saving MQTT data ${JSON.stringify(data)} to local storage`);
    localStorage.setItem("pin", data.pin);
    localStorage.setItem("mqtt_host", data.mqtt_host);
    localStorage.setItem("mqtt_port", data.mqtt_port);
    localStorage.setItem("mqtt_version", data.mqtt_version);
    localStorage.setItem("mqtt_use_ssl", data.mqtt_use_ssl);
    localStorage.setItem("mqtt_username", data.mqtt_username);
    localStorage.setItem("mqtt_password", data.mqtt_password);

    localStorage.setItem("date", Date.now());
};