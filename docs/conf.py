# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "OpenOptics"
copyright = "2025, Network and Cloud Systems Group, MPI-INF"
author = "Yiming Lei"
version = "0.0.1"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.viewcode",
    "sphinx.ext.napoleon",
    "sphinx.ext.autosectionlabel",
    "myst_parser",  # md
]

autosummary_generate = True
autosectionlabel_prefix_document = True
autodoc_member_order = "bysource"

autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
}

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_static_path = ["_static"]

html_theme = "alabaster"
html_theme = "pydata_sphinx_theme"
"""
html_theme_options = {
    "navigation_depth": 3,
    "show_nav_level": 2,
    "collapse_navigation": False,
    "footer_start": ["copyright"],
    #"footer_end": ["tem_author"],
    "github_url" : "www.github.com"
}
html_sidebars = {
    "**": ["sidebar-nav-bs"]
}
"""
html_theme = "sphinx_book_theme"

html_logo = "_static/openoptics_words.svg"
html_favicon = "_static/openoptics.ico"

html_theme_options = {
    "show_toc_level": 2,
    "show_navbar_depth": 2,
    # "search_bar_text": "Search this book...",
}

html_context = {
    "display_github": True,
    "github_user": "ymlei",
    "github_repo": "",
    "github_version": "main",
    "conf_py_path": "/docs/",
}

"""
html_sidebars = {
    "**": ["navbar-logo.html",  "search-field.html", "sbt-sidebar-nav.html"]
}
"""

autodoc_mock_imports = [
    "networkx",
    "tswitch_CLI",
    "runtime_CLI",
    "django",
    "matplotlib",
    "mininet",
]

exclude_patterns = [
    "tutorial/*",
]
