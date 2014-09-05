%global python_site_packages %(python3 -c "from distutils.sysconfig import get_python_lib; import sys; sys.stdout.write(get_python_lib())")

Name:		virtme
Version:	0.0.1
Release:	1%{?dist}
Summary:	virtualized host helper for rapid kernel testing

Group:		kernel
License:	GPLv2
URL:		https://github.com/amluto/virtme
Source0:	virtme-0.0.1.tar.gz

BuildRequires:	python3
Requires:	python3

%description
%{summary}.

%prep
%setup -q


%build
python3 setup.py build


%install
python3 setup.py install --root %{buildroot}


%files
%doc
%{_bindir}/virtme-init
%{_bindir}/virtme-loadmods
%{_bindir}/virtme-mkinitramfs
%{_bindir}/virtme-run
%{_bindir}/virtme-udhcpc-script
%{python_site_packages}/virtme-0.0.1-py3.3.egg-info
%{python_site_packages}/virtme/__pycache__/architectures.cpython-33.pyc
%{python_site_packages}/virtme/__pycache__/architectures.cpython-33.pyo
%{python_site_packages}/virtme/__pycache__/cpiowriter.cpython-33.pyc
%{python_site_packages}/virtme/__pycache__/cpiowriter.cpython-33.pyo
%{python_site_packages}/virtme/__pycache__/mkinitramfs.cpython-33.pyc
%{python_site_packages}/virtme/__pycache__/mkinitramfs.cpython-33.pyo
%{python_site_packages}/virtme/__pycache__/modfinder.cpython-33.pyc
%{python_site_packages}/virtme/__pycache__/modfinder.cpython-33.pyo
%{python_site_packages}/virtme/__pycache__/qemu_helpers.cpython-33.pyc
%{python_site_packages}/virtme/__pycache__/qemu_helpers.cpython-33.pyo
%{python_site_packages}/virtme/__pycache__/virtmods.cpython-33.pyc
%{python_site_packages}/virtme/__pycache__/virtmods.cpython-33.pyo
%{python_site_packages}/virtme/architectures.py
%{python_site_packages}/virtme/cpiowriter.py
%{python_site_packages}/virtme/mkinitramfs.py
%{python_site_packages}/virtme/modfinder.py
%{python_site_packages}/virtme/qemu_helpers.py
%{python_site_packages}/virtme/virtmods.py



%changelog

