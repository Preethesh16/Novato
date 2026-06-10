# Maintainer: Novato contributors <novato@example.com>
pkgname=novato
pkgver=0.1.0
pkgrel=1
pkgdesc="A Linux terminal companion: install by intent, catch errors, learn as you go"
arch=('any')
url="https://github.com/Preethesh16/Novato"
license=('MIT')
depends=(
    'python'
    'python-click'
    'python-rich'
    'python-distro'
    'python-requests'
    'python-psutil'
)
makedepends=(
    'python-build'
    'python-installer'
    'python-wheel'
    'python-hatchling'
)
optdepends=(
    'yay: AUR package installation support'
    'paru: AUR package installation support'
)
source=("$pkgname-$pkgver.tar.gz::$url/archive/refs/tags/v$pkgver.tar.gz")
sha256sums=('SKIP')

build() {
    cd "$srcdir/Novato-$pkgver"
    python -m build --wheel --no-isolation
}

check() {
    cd "$srcdir/Novato-$pkgver"
    # Tests are offline and hermetic; skip if pytest is unavailable.
    if python -c 'import pytest' 2>/dev/null; then
        python -m pytest -q
    fi
}

package() {
    cd "$srcdir/Novato-$pkgver"
    python -m installer --destdir="$pkgdir" dist/*.whl
    install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
    install -Dm644 README.md "$pkgdir/usr/share/doc/$pkgname/README.md"
    install -Dm644 DOCUMENTATION.md "$pkgdir/usr/share/doc/$pkgname/DOCUMENTATION.md"
}
