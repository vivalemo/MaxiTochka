"""Патч selenium-wire / mitmproxy для pyOpenSSL 24+ (сертификаты через cryptography)."""

from __future__ import annotations

import datetime
import ipaddress
import time


def apply_seleniumwire_patch() -> None:
    if apply_seleniumwire_patch._done:  # type: ignore[attr-defined]
        return

    try:
        from seleniumwire.thirdparty.mitmproxy import certs
    except ImportError:
        return

    from OpenSSL import crypto
    from cryptography import x509 as cx509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    from pyasn1.codec.der.decoder import decode
    from pyasn1.error import PyAsn1Error

    _GeneralNames = certs._GeneralNames

    def altnames(self) -> list:
        x509_obj = self.x509
        altnames: list = []

        if hasattr(x509_obj, "get_extension"):
            for i in range(x509_obj.get_extension_count()):
                ext = x509_obj.get_extension(i)
                if ext.get_short_name() == b"subjectAltName":
                    try:
                        dec = decode(ext.get_data(), asn1Spec=_GeneralNames())
                    except PyAsn1Error:
                        continue
                    for entry in dec[0]:
                        if entry[0].hasValue():
                            altnames.append(entry[0].asOctets())
            return altnames

        try:
            crypto_cert = x509_obj.to_cryptography()
            san = crypto_cert.extensions.get_extension_for_class(
                cx509.SubjectAlternativeName
            )
            for name in san.value:
                if isinstance(name, cx509.DNSName):
                    val = name.value
                    altnames.append(val.encode("ascii") if isinstance(val, str) else val)
        except Exception:
            pass

        return altnames

    def _san_extension(sans) -> cx509.SubjectAlternativeName:
        names = []
        for item in sans:
            s = item.decode("ascii") if isinstance(item, bytes) else str(item)
            try:
                names.append(cx509.IPAddress(ipaddress.ip_address(s)))
            except ValueError:
                names.append(cx509.DNSName(s))
        return cx509.SubjectAlternativeName(names)

    def create_ca(organization, cn, exp, key_size):
        key_crypto = rsa.generate_private_key(public_exponent=65537, key_size=key_size)
        subject = issuer = cx509.Name(
            [
                cx509.NameAttribute(NameOID.COMMON_NAME, cn),
                cx509.NameAttribute(NameOID.ORGANIZATION_NAME, organization),
            ]
        )
        now = datetime.datetime.now(datetime.timezone.utc)
        builder = (
            cx509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key_crypto.public_key())
            .serial_number(int(time.time() * 10000))
            .not_valid_before(now - datetime.timedelta(hours=48))
            .not_valid_after(now + datetime.timedelta(seconds=exp))
            .add_extension(
                cx509.BasicConstraints(ca=True, path_length=None), critical=True
            )
            .add_extension(
                cx509.ExtendedKeyUsage(
                    [
                        ExtendedKeyUsageOID.SERVER_AUTH,
                        ExtendedKeyUsageOID.CLIENT_AUTH,
                        ExtendedKeyUsageOID.EMAIL_PROTECTION,
                        ExtendedKeyUsageOID.TIME_STAMPING,
                    ]
                ),
                critical=False,
            )
            .add_extension(
                cx509.KeyUsage(
                    digital_signature=False,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=True,
                    crl_sign=True,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
        )
        cert_crypto = builder.sign(key_crypto, hashes.SHA256())
        return (
            crypto.PKey.from_cryptography_key(key_crypto),
            crypto.X509.from_cryptography(cert_crypto),
        )

    def dummy_cert(privkey, cacert, commonname, sans, organization):
        ca_x509 = cacert.to_cryptography()
        sign_key = privkey.to_cryptography_key()

        attrs = []
        cn_valid = commonname is not None and len(commonname) < 64
        if cn_valid:
            cn = commonname.decode() if isinstance(commonname, bytes) else commonname
            attrs.append(cx509.NameAttribute(NameOID.COMMON_NAME, cn))
        if organization is not None:
            org = organization.decode() if isinstance(organization, bytes) else organization
            attrs.append(cx509.NameAttribute(NameOID.ORGANIZATION_NAME, org))

        subject = cx509.Name(attrs) if attrs else cx509.Name([])
        now = datetime.datetime.now(datetime.timezone.utc)

        builder = (
            cx509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(ca_x509.subject)
            .public_key(ca_x509.public_key())
            .serial_number(int(time.time() * 10000))
            .not_valid_before(now - datetime.timedelta(hours=48))
            .not_valid_after(
                now + datetime.timedelta(seconds=certs.DEFAULT_EXP_DUMMY_CERT)
            )
        )

        if sans:
            san_ext = _san_extension(sans)
            builder = builder.add_extension(san_ext, critical=not cn_valid)

        builder = builder.add_extension(
            cx509.ExtendedKeyUsage(
                [ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]
            ),
            critical=False,
        )

        cert_crypto = builder.sign(sign_key, hashes.SHA256())
        return certs.Cert(crypto.X509.from_cryptography(cert_crypto))

    certs.Cert.altnames = property(altnames)
    certs.create_ca = create_ca
    certs.dummy_cert = dummy_cert

    _patch_seleniumwire_ca_bundle()
    apply_seleniumwire_patch._done = True  # type: ignore[attr-defined]


def _patch_seleniumwire_ca_bundle() -> None:
    """В .exe pkgutil.get_data('ca.crt') часто пустой — подгружаем сертификаты явно."""
    import os
    import pkgutil
    from pathlib import Path

    import seleniumwire.utils as sw_utils

    if getattr(sw_utils, "_mx_ca_patched", False):
        return

    orig = sw_utils.extract_cert_and_key

    def _load_ca_bytes() -> tuple[bytes, bytes]:
        cert = pkgutil.get_data("seleniumwire", sw_utils.ROOT_CERT)
        key = pkgutil.get_data("seleniumwire", sw_utils.ROOT_KEY)
        if cert and key:
            return cert, key

        try:
            import importlib.resources as res

            root = res.files("seleniumwire")
            cert = root.joinpath(sw_utils.ROOT_CERT).read_bytes()
            key = root.joinpath(sw_utils.ROOT_KEY).read_bytes()
            return cert, key
        except Exception:
            pass

        # PyInstaller onedir: рядом с пакетом в _internal/seleniumwire/
        try:
            import seleniumwire

            base = Path(seleniumwire.__file__).resolve().parent
            cert_path = base / sw_utils.ROOT_CERT
            key_path = base / sw_utils.ROOT_KEY
            if cert_path.is_file() and key_path.is_file():
                return cert_path.read_bytes(), key_path.read_bytes()
        except Exception:
            pass

        raise FileNotFoundError(
            "Не найдены ca.crt/ca.key для selenium-wire. "
            "Переустановите сборку Maxitochka (полная папка dist\\Maxitochka)."
        )

    def extract_cert_and_key(dest_folder, cert_path=None, key_path=None, check_exists=True):
        if cert_path is not None or key_path is not None:
            return orig(dest_folder, cert_path, key_path, check_exists)

        os.makedirs(dest_folder, exist_ok=True)
        combined = Path(dest_folder) / sw_utils.COMBINED_CERT
        if check_exists and combined.exists():
            return

        root_cert, root_key = _load_ca_bytes()
        with open(combined, "wb") as f_out:
            f_out.write(root_cert + b"\n" + root_key)

    sw_utils.extract_cert_and_key = extract_cert_and_key
    sw_utils._mx_ca_patched = True


apply_seleniumwire_patch._done = False  # type: ignore[attr-defined]
