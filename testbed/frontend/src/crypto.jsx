// import hkdf from "futoin-hkdf";
import * as jose from 'jose'
import { hkdf } from '@noble/hashes/hkdf.js';
import { sha256 } from '@noble/hashes/sha2.js';
import * as utils from '@noble/hashes/utils.js';
const { utf8ToBytes } = utils;


// import packagejson from '../../package.json';

// import semverMajor from 'semver/functions/major';
// import semverMinor from 'semver/functions/minor';

import logger from './logger';
const log = logger.child({ module: 'crypto' });

const _parsedVersion = `0.9`;


function base64FromBytes(bytes) {
    let binary = '';
    const len = bytes.length;
    for (let i = 0; i < len; i++) {
        binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary);
}

// const _parsedVersion = `${semverMajor(packagejson.version)}.${semverMinor(packagejson.version)}`;

// export const deriveKey = (pin) => {
//     const length = 32;
//     const salt = '';
//     const info = `secret_key_${_parsedVersion}`;
//     const hash = 'SHA-256';

//     return hkdf(`${pin}`, length, { salt, info, hash });
// };

export const deriveKey = (pin) => {
    console.log(`pin: ${pin}`)
    const length = 32;
    const salt = new Uint8Array(0);
    const info = utf8ToBytes(`secret_key_${String(_parsedVersion)}`);
    const keyBytes = hkdf(sha256, utf8ToBytes(String(pin)), salt, info, length);

    console.log(`key: ${keyBytes}`)
    const text = new TextDecoder().decode(keyBytes);
    console.log(`keyastext: ${text}`)
    console.log(`keyasbase64: ${base64FromBytes(keyBytes)}`)


    return keyBytes;
};


// export const deriveTopic = (pin) => {
//     const length = 16;
//     const salt = '';
//     const info = `secret_topic_${_parsedVersion}`;
//     const hash = 'SHA-256';

//     // Topic is encoded in url safe base64
//     return Buffer.from(hkdf(`${pin}`, length, { salt, info, hash })).toString("base64").replace(/\+/g, '-').replace(/\//g, '_');
// };

export const deriveTopic = (pin) => {
    const length = 16;
    const salt = new Uint8Array(0);
    const info = utf8ToBytes(`secret_topic_${_parsedVersion}`);

    const keyBytes = hkdf(sha256, utf8ToBytes(pin), salt, info, length);

    // Topic is encoded in url safe base64
    return base64FromBytes(keyBytes).replace(/\+/g, '-').replace(/\//g, '_');
};


export const encrypt = async (message, key) => {
    const jwe = await new jose.CompactEncrypt(
        new TextEncoder().encode(message),
    )
        .setProtectedHeader({ alg: 'dir', enc: 'A256GCM' })
        .encrypt(key)
    return jwe;
};

export const decrypt = async (message, key) => {
    try {
        const decrypted = await jose.compactDecrypt(message, key)
        return new TextDecoder().decode(decrypted.plaintext);
    } catch (error) {
        log.debug(`${error.name}: ${error.message}`);
        return;
    }
};