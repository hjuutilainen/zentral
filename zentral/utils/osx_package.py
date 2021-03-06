from itertools import chain
import os
import plistlib
import shutil
from subprocess import check_call, check_output
import tempfile
import xml.etree.ElementTree as ET
from django.http import HttpResponse


class PackageBuilder(object):
    package_name = None
    build_tmpl_dir = None
    with_package_signature = True

    def __init__(self):
        # build template dir
        build_tmpl_dir = self.get_build_tmpl_dir()
        if not os.path.isdir(build_tmpl_dir):
            raise ValueError("build tmpl dir is not a dir")
        self.build_tmpl_dir = build_tmpl_dir
        # package name
        package_name = self.get_package_name()
        if not isinstance(package_name, str):
            raise TypeError("package name must be a str")
        if not package_name:
            raise ValueError("package name is an empty")
        if not package_name.endswith(".pkg"):
            package_name = "{}.pkg".format(package_name)
        self.package_name = package_name

    #
    # common build steps
    #

    def _prepare_temporary_build_dir(self):
        self.tempdir = tempfile.mkdtemp(suffix=self.__module__)
        self.builddir = os.path.join(self.tempdir, "build")
        shutil.copytree(self.build_tmpl_dir, self.builddir)

    def _prepare_package_info(self, package_identifier, version):
        number_of_files = install_bytes = 0
        for root, dirs, files in os.walk(self.get_root_path()):
            for name in chain(dirs, files):
                number_of_files += 1
                install_bytes += os.path.getsize(os.path.join(root, name))
        number_of_files = str(number_of_files)
        install_kbytes = str(install_bytes // 1024)
        self.replace_in_file(self.get_build_path("base.pkg", "PackageInfo"),
                             (("%NUMBER_OF_FILES%", number_of_files),
                              ("%INSTALL_KBYTES%", install_kbytes),
                              ("%PKG_IDENTIFIER%", package_identifier),
                              ("%VERSION%", version),))
        return number_of_files, install_kbytes

    def _build_gziped_cpio_arch(self, dirname, arch_name):
        input_path = self.get_build_path(dirname)
        output_path = self.get_build_path("base.pkg", arch_name)
        check_call('(cd "{}" && find . | '
                   'cpio -o --quiet --format odc --owner 0:80 | '
                   'gzip -c) > "{}"'.format(input_path, output_path), shell=True)

    def _build_payload(self):
        self._build_gziped_cpio_arch("root", "Payload")

    def _build_scripts(self):
        self._build_gziped_cpio_arch("scripts", "Scripts")

    def _build_bom(self):
        check_call(["/usr/bin/mkbom", "-u", "0", "-g", "80",
                    self.get_root_path(),
                    self.get_build_path("base.pkg", "Bom")])

    def _extract_product_archive(self, base_product_archive):
        pa_path = os.path.join(self.tempdir, "product_archive")
        os.mkdir(pa_path)
        check_call('cd "{}" && '
                   '/usr/local/bin/xar -xf "{}"'.format(pa_path,
                                                        base_product_archive),
                   shell=True)
        return pa_path

    def _add_package_to_distribution(self, pa_path, package_identifier, install_kbytes, version):
        distribution_file = os.path.join(pa_path, "Distribution")
        tree = ET.parse(distribution_file)
        installer_script = tree.getroot()
        # Add line to choices-outline
        choice_id, _ = os.path.splitext(self.package_name)
        choices_outline = tree.find("choices-outline")
        line = ET.Element("line")
        line.set("choice", choice_id)
        choices_outline.append(line)
        # Add choice
        choice = ET.Element("choice")
        choice.set("id", choice_id)
        choice.set("title", "{} title".format(choice_id))
        choice.set("description", "{} description".format(choice_id))
        pkg_ref = ET.Element("pkg-ref")
        pkg_ref.set("id", package_identifier)
        choice.append(pkg_ref)
        installer_script.append(choice)
        # Add first pkg-ref
        pkg_ref = ET.Element("pkg-ref")
        pkg_ref.set("id", package_identifier)
        pkg_ref.set("installKBytes", install_kbytes)
        pkg_ref.set("version", version)
        pkg_ref.set("auth", "Root")
        pkg_ref.text = "#{}".format(self.package_name)
        installer_script.append(pkg_ref)
        # Add second pkg-ref
        pkg_ref = ET.Element("pkg-ref")
        pkg_ref.set("id", package_identifier)
        bundle_version = ET.Element("bundle-version")
        pkg_ref.append(bundle_version)
        installer_script.append(pkg_ref)
        # write new Distribution
        tree.write(distribution_file)

    def _build_pkg(self, pkg_dir, filename):
        pkg_path = os.path.join(self.tempdir, filename)
        check_call('cd "{}" && '
                   '/usr/local/bin/xar '
                   '--compression none -cf "{}" *'.format(pkg_dir, pkg_path),
                   shell=True)
        return pkg_path

    def _get_signature_size(self, private_key):
        return len(check_output(": | openssl dgst -sign '{}' -binary".format(private_key), shell=True))

    def _add_cert_and_get_digest_info(self, pkg_path, certificate, signature_size):
        digest_info_file = os.path.join(self.tempdir, "digestinfo.dat")
        check_call(["/usr/local/bin/xar", "--sign",
                    "-f", pkg_path,
                    "--digestinfo", digest_info_file,
                    "--sig-size", str(signature_size),
                    "--cert-loc", certificate])
        return digest_info_file

    def _sign_digest_info(self, digest_info_file, private_key):
        signature_file = os.path.join(self.tempdir, "signature.dat")
        check_call(["/usr/bin/openssl", "rsautl", "-sign",
                    "-inkey", private_key,
                    "-in", digest_info_file,
                    "-out", signature_file])
        return signature_file

    def _inject_signature(self, signature_file, pkg_path):
        check_call(["/usr/local/bin/xar",
                    "--inject-sig", signature_file,
                    "-f", pkg_path])

    def _sign_pkg(self, pkg_path, certificate, private_key):
        signature_size = self._get_signature_size(private_key)
        digest_info_file = self._add_cert_and_get_digest_info(pkg_path, certificate, signature_size)
        signature_file = self._sign_digest_info(digest_info_file, private_key)
        self._inject_signature(signature_file, pkg_path)

    def _clean(self):
        shutil.rmtree(self.tempdir)

    #
    # API
    #

    # default settings

    def get_package_name(self):
        return self.package_name

    def get_build_tmpl_dir(self):
        return self.build_tmpl_dir

    # build

    def extra_build_steps(self, *args, **kwargs):
        pass

    def get_package_identifier(self, business_unit):
        package_identifier = self.package_identifier
        if business_unit:
            package_identifier = "{}.bu_{}".format(package_identifier,
                                                   business_unit.get_short_key())
        return package_identifier

    def build(self, business_unit, *args, **kwargs):
        version = kwargs.pop('version', '1.0')
        certificate = kwargs.pop("package_signature_certificate", None)
        private_key = kwargs.pop("package_signature_private_key", None)
        base_product_archive = kwargs.pop("base_product_archive", None)
        product_archive_name = kwargs.pop("product_archive_name", None)

        self._prepare_temporary_build_dir()
        self.extra_build_steps(*args, **kwargs)
        package_identifier = self.get_package_identifier(business_unit)
        _, install_kbytes = self._prepare_package_info(package_identifier, version)
        self._build_payload()
        self._build_scripts()
        self._build_bom()
        # TODO: memory
        if base_product_archive:
            pa_path = self._extract_product_archive(base_product_archive)
            shutil.move(self.get_build_path("base.pkg"), os.path.join(pa_path, self.package_name))
            self._add_package_to_distribution(pa_path, package_identifier, install_kbytes, version)
            pkg_dir = pa_path
            filename = product_archive_name
        else:
            pkg_dir = self.get_build_path("base.pkg")
            filename = self.package_name
        pkg_path = self._build_pkg(pkg_dir, filename)
        if certificate and private_key:
            self._sign_pkg(pkg_path, certificate, private_key)
        with open(pkg_path, 'rb') as f:
            content = f.read()
        self._clean()
        return content, filename

    def build_and_make_response(self, *args, **kwargs):
        content, filename = self.build(*args, **kwargs)
        # TODO: memory
        response = HttpResponse(content, "application/octet-stream")
        response['Content-Length'] = len(content)
        response['Content-Disposition'] = 'attachment; filename="{}"'.format(filename)
        return response

    # build tools

    def get_build_path(self, *args):
        return os.path.join(self.builddir, *args)

    def get_root_path(self, *args):
        return self.get_build_path("root", *args)

    def replace_in_file(self, filename, patterns):
        with open(filename, "r", encoding="utf-8") as f:
            content = f.read()
        for pattern, replacement in patterns:
            content = content.replace(pattern, replacement)
        with open(filename, "w", encoding="utf-8") as f:
            f.write(content)

    def set_plist_keys(self, filename, keyvals):
        with open(filename, "rb") as f:
            pl = plistlib.load(f)
        for key, val in keyvals:
            pl[key] = val
        with open(filename, "wb") as f:
            plistlib.dump(pl, f)

    def append_to_plist_key(self, filename, key, val):
        with open(filename, "rb") as f:
            pl = plistlib.load(f)
        pl.setdefault(key, []).append(val)
        with open(filename, "wb") as f:
            plistlib.dump(pl, f)
