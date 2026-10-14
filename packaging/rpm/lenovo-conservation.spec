Name:           lenovo-conservation
Version:        1.0.0
Release:        1%{?dist}
Summary:        Cross-Distribution Lenovo Battery Conservation App for Linux

License:        GPLv3+
URL:            https://github.com/lenovo-conservation/lenovo-conservation
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  python3-devel
BuildRequires:  python3-setuptools
Requires:       python3
Requires:       python3-pyside6
Requires:       polkit
Requires:       systemd

%description
Lenovo Conservation manages battery charging limits and conservation mode
for Lenovo laptops (IdeaPad, ThinkPad, Legion, LOQ, and IdeaPad Gaming series)
under Linux desktop environments.

%prep
%autosetup

%build
%py3_build

%install
%py3_install
install -Dm755 bin/lenovo-conservation-helper %{buildroot}%{_libexecdir}/lenovo-conservation-helper
install -Dm644 data/lenovo-conservation.desktop %{buildroot}%{_datadir}/applications/lenovo-conservation.desktop
install -Dm644 data/icons/lenovo-conservation.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/lenovo-conservation.svg
install -Dm644 data/org.lenovo.conservation.policy %{buildroot}%{_datadir}/polkit-1/actions/org.lenovo.conservation.policy
install -Dm644 data/lenovo-conservation.service %{buildroot}%{_unitdir}/lenovo-conservation.service

%post
%systemd_post lenovo-conservation.service

%preun
%systemd_preun lenovo-conservation.service

%postun
%systemd_postun_with_restart lenovo-conservation.service

%files
%license LICENSE
%doc README.md
%{_bindir}/lenovo-conservation
%{_bindir}/lenovo-conservation-daemon
%{_libexecdir}/lenovo-conservation-helper
%{python3_sitelib}/lenovo_conservation/
%{python3_sitelib}/lenovo_conservation*.egg-info
%{_datadir}/applications/lenovo-conservation.desktop
%{_datadir}/icons/hicolor/scalable/apps/lenovo-conservation.svg
%{_datadir}/polkit-1/actions/org.lenovo.conservation.policy
%{_unitdir}/lenovo-conservation.service

%changelog
* Wed Oct 14 2026 Lenovo Conservation Contributors <contact@lenovo-conservation.org> - 1.0.0-1
- Initial release for Fedora, openSUSE, and enterprise Linux
