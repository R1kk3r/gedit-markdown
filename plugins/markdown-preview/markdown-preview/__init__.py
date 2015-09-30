#!/usr/bin/python
# -*- coding: utf-8 -*-

# HTML preview of Markdown formatted text in gedit
# Copyright © 2005, 2006 Michele Campeotto
# Copyright © 2009 Jean-Philippe Fleury <contact@jpfleury.net>

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


###########
# IMPORTS #
###########
from gi.repository import Gio, Gdk, Gtk, Gedit, GObject, WebKit, GLib
import codecs
import os
import sys
import markdown
import gettext
from configparser import SafeConfigParser
import webbrowser


##################
# INITIALIZATION #
##################

# Internationalization
try:
	appName = "markdown-preview"
	fileDir = os.path.dirname(__file__)
	localePath = os.path.join(fileDir, "locale")
	gettext.bindtextdomain(appName, localePath)
	_ = lambda s: gettext.dgettext(appName, s);
except:
	_ = lambda s: s

# Can be used to add default HTML code (e.g. default header section with CSS).
htmlTemplate = "%s"

# Default configuration.
markdownExternalBrowser = "0"
markdownPanel = "bottom"
markdownShortcut = "<Control><Alt>m"
markdownVersion = "extra"
markdownVisibility = "1"
markdownVisibilityShortcut = "<Control><Alt>v"

# Load confguration from file
try:
	import xdg.BaseDirectory
except ImportError:
	homeDir = os.environ.get("HOME")
	xdgConfigHome = os.path.join(homeDir, ".config")
else:
	xdgConfigHome = xdg.BaseDirectory.xdg_config_home

confDir =  os.path.join(xdgConfigHome, "gedit")
confFile =  os.path.join(confDir, "gedit-markdown.ini")

parser = SafeConfigParser()
parser.optionxform = str
parser.add_section("markdown-preview")
parser.set("markdown-preview", "externalBrowser", markdownExternalBrowser)
parser.set("markdown-preview", "panel", markdownPanel)
parser.set("markdown-preview", "shortcut", markdownShortcut)
parser.set("markdown-preview", "version", markdownVersion)
parser.set("markdown-preview", "visibility", markdownVisibility)
parser.set("markdown-preview", "visibilityShortcut", markdownVisibilityShortcut)

if os.path.isfile(confFile):
	parser.read(confFile)
	markdownExternalBrowser = parser.get("markdown-preview", "externalBrowser")
	markdownPanel = parser.get("markdown-preview", "panel")
	markdownShortcut = parser.get("markdown-preview", "shortcut")
	markdownVersion = parser.get("markdown-preview", "version")
	markdownVisibility = parser.get("markdown-preview", "visibility")
	markdownVisibilityShortcut = parser.get("markdown-preview", "visibilityShortcut")

if not os.path.exists(confDir):
	os.makedirs(confDir)

with open(confFile, "w") as confFile:
	parser.write(confFile)

#################################
# MarkdownPreviewAppActivatable #
#################################

class MarkdownPreviewAppActivatable(GObject.Object, Gedit.AppActivatable):
	app = GObject.property(type=Gedit.App)
	
	def __init__(self):
		GObject.Object.__init__(self)
	
	def do_activate(self):
		markdownPrevItem = Gio.MenuItem.new(_("Update Markdown Preview"), "win.MarkdownPreview")
		toggleTabItem = Gio.MenuItem.new(_("Toggle Markdown Preview visibility"), "win.ToggleTab")

		self.menu_ext = self.extend_menu("tools-section")

		self.menu_ext.prepend_menu_item(markdownPrevItem)
		self.menu_ext.prepend_menu_item(toggleTabItem)

		self.app.add_accelerator(markdownShortcut, "win.MarkdownPreview", None);
		self.app.add_accelerator(markdownVisibilityShortcut, "win.ToggleTab", None);
	
	def do_deactivate(self):
		self.menu_ext = None

####################################
# MarkdownPreviewWindowActivatable #
####################################

class MarkdownPreviewWindowActivatable(GObject.Object, Gedit.WindowActivatable):
	window = GObject.property(type=Gedit.Window)
	markdownPrevAction = None
	toogleTabAction = None
	currentUri = ""
	overLinkUrl = ""

	def __init__(self):
		GObject.Object.__init__(self)

	def do_activate(self):
		self.markdownPrevAction = Gio.SimpleAction.new("MarkdownPreview",None)
		self.toggleTabAction = Gio.SimpleAction.new_stateful("ToggleTab",None, GLib.Variant.new_boolean(markdownVisibility != 0))

		self.markdownPrevAction.connect('activate', lambda x, y: self.updatePreview(y, False))
		self.toggleTabAction.connect('change-state', self.toggleTab)

		self.window.add_action(self.markdownPrevAction)
		self.window.add_action(self.toggleTabAction)

		self.scrolledWindow = Gtk.ScrolledWindow()
		self.scrolledWindow.set_property("hscrollbar-policy", Gtk.PolicyType.AUTOMATIC)
		self.scrolledWindow.set_property("vscrollbar-policy", Gtk.PolicyType.AUTOMATIC)
		self.scrolledWindow.set_property("shadow-type", Gtk.ShadowType.IN)

		self.htmlView = WebKit.WebView()
		self.htmlView.connect("hovering-over-link", self.onHoveringOverLinkCb)
		self.htmlView.connect("navigation-policy-decision-requested",
		                       self.onNavigationPolicyDecisionRequestedCb)
		self.htmlView.connect("populate-popup", self.onPopulatePopupCb)
		
		self.htmlView.load_string((htmlTemplate % ("", )), "text/html", "utf-8", "file:///")
		
		self.scrolledWindow.add(self.htmlView)
		self.scrolledWindow.show_all()
		
		if markdownVisibility == "1":
			self.addMarkdownPreviewTab()

	def do_deactivate(self):
		self.window.remove_action("MarkdownPreview")
		self.window.remove_action("ToggleTab")
		self.markdownPrevAction = None
		self.toggleTabAction = None
		
		self.removeMarkdownPreviewTab()

	def do_update_state(self):
		if self.markdownPrevAction is not None:
			self.markdownPrevAction.set_enabled(self.window.get_active_document() is not None)
		if self.toggleTabAction is not None:
			self.toggleTabAction.set_enabled(self.window.get_active_document() is not None)
	
	def addMarkdownPreviewTab(self):
		if markdownPanel == "side":
			stack = self.window.get_side_panel()
		else:
			stack = self.window.get_bottom_panel()

		stack.connect("hide",self.onStackClose);
		stack.add_titled(self.scrolledWindow, "MarkdownPreview", _("Markdown Preview"))
		stack.show()
		stack.set_visible_child(self.scrolledWindow)

	def removeMarkdownPreviewTab(self):
		if markdownPanel == "side":
			stack = self.window.get_side_panel()
		else:
			stack = self.window.get_bottom_panel()
		
		stack.remove(self.scrolledWindow)
	
	def onStackClose(self, nothing):
		if self.toggleTabAction is not None:
			self.toggleTabAction.set_state(GLib.Variant.new_boolean(False))

	def toggleTab(self, action, state):
		action.set_state(state)

		if markdownPanel == "side":
			stack = self.window.get_side_panel()
		else:
			stack = self.window.get_bottom_panel()
		
		if not state:
			stack.hide()
		else:
			stack.show()

	def copyCurrentUrl(self):
		self.clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
		self.clipboard.set_text(self.currentUri, -1)
	
	def goToAnotherUrl(self):
		newUrl = self.goToAnotherUrlDialog()
		
		if newUrl:
			if newUrl.startswith("/"):
				newUrl = "file://" + newUrl
			
			self.htmlView.open(newUrl)
	
	def goToAnotherUrlDialog(self):
		dialog = Gtk.MessageDialog(None,
		                           Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
		                           Gtk.MessageType.QUESTION,
		                           Gtk.ButtonsType.OK_CANCEL,
		                           _("Enter URL"))
		dialog.set_title(_("Enter URL"))
		dialog.format_secondary_markup(_("Enter the URL (local or distant) of the document or page to display."))
		
		entry = Gtk.Entry()
		entry.connect("activate", self.onGoToAnotherUrlDialogActivateCb, dialog,
		              Gtk.ResponseType.OK)
		
		dialog.vbox.pack_end(entry, True, True, 0)
		dialog.show_all()
		
		response = dialog.run()
		
		newUrl = ""
		
		if response == Gtk.ResponseType.OK:
			newUrl = entry.get_text()
		
		dialog.destroy()
		
		return newUrl
	
	def onGoToAnotherUrlDialogActivateCb(self, entry, dialog, response):
		dialog.response(response)
	
	def onHoveringOverLinkCb(self, page, title, url):
		if url and not self.overLinkUrl:
			self.overLinkUrl = url
			
			self.urlTooltip = Gtk.Window.new(Gtk.WindowType.POPUP)
			self.urlTooltip.set_border_width(2)
			self.urlTooltip.modify_bg(0, Gdk.color_parse("#d9d9d9"))
			
			label = Gtk.Label()
			text = (url[:75] + "...") if len(url) > 75 else url
			label.set_text(text)
			label.modify_fg(0, Gdk.color_parse("black"))
			self.urlTooltip.add(label)
			label.show()
			
			self.urlTooltip.show()
			
			xPointer, yPointer = self.urlTooltip.get_pointer()
			
			xWindow = self.window.get_position()[0]
			widthWindow = self.window.get_size()[0]
			
			widthUrlTooltip = self.urlTooltip.get_size()[0]
			xUrlTooltip = xPointer
			yUrlTooltip = yPointer + 15
			
			xOverflow = (xUrlTooltip + widthUrlTooltip) - (xWindow + widthWindow)
			
			if xOverflow > 0:
				xUrlTooltip = xUrlTooltip - xOverflow
			
			self.urlTooltip.move(xUrlTooltip, yUrlTooltip)
		else:
			self.overLinkUrl = ""
			
			if self.urlTooltipVisible():
				self.urlTooltip.destroy()
	
	def onNavigationPolicyDecisionRequestedCb(self, view, frame, networkRequest,
	                                          navAct, polDec):
		self.currentUri = networkRequest.get_uri()
		
		if self.currentUri == "file:///":
			activeDocument = self.window.get_active_document()
			
			if activeDocument:
				uriActiveDocument = activeDocument.get_uri_for_display()
				
				# Make sure we have an absolute path (so the file exists).
				if uriActiveDocument.startswith("/"):
					self.currentUri = uriActiveDocument
		
		if navAct.get_reason().value_nick == "link-clicked" and markdownExternalBrowser == "1":
			webbrowser.open_new_tab(self.currentUri)
			
			if self.urlTooltipVisible():
				self.urlTooltip.destroy()
			
			polDec.ignore()
		
		return False
	
	def openInEmbeddedBrowser(self):
		self.htmlView.open(self.overLinkUrl)
	
	def openInExternalBrowser(self):
		webbrowser.open_new_tab(self.overLinkUrl)
	
	def onPopulatePopupCb(self, view, menu):
		if self.urlTooltipVisible():
			self.urlTooltip.destroy()
		
		for item in menu.get_children():
			try:
				icon = item.get_image().get_stock()[0]
				
				if (icon == "gtk-copy" or icon == "gtk-go-back" or
				    icon == "gtk-go-forward" or icon == "gtk-stop"):
					continue
				elif icon == "gtk-refresh":
					if self.currentUri == "file:///":
						item.set_sensitive(False)
				else:
					menu.remove(item)
			except:
				menu.remove(item)
		
		if self.overLinkUrl:
			if markdownExternalBrowser == "1":
				item = Gtk.MenuItem(label=_("Open in the embedded browser"))
				item.connect("activate", lambda x: self.openInEmbeddedBrowser())
			else:
				item = Gtk.MenuItem(label=_("Open in an external browser"))
				item.connect("activate", lambda x: self.openInExternalBrowser())
			
			menu.append(item)
		
		item = Gtk.MenuItem(label=_("Copy the current URL"))
		item.connect("activate", lambda x: self.copyCurrentUrl())
		
		if self.currentUri == "file:///":
			item.set_sensitive(False)
		
		menu.append(item)
		
		item = Gtk.MenuItem(label=_("Go to another URL"))
		item.connect("activate", lambda x: self.goToAnotherUrl())
		menu.append(item)
		
		item = Gtk.MenuItem(label=_("Update Preview"))
		item.connect("activate", lambda x: self.updatePreview(self, False))
		
		documents = self.window.get_documents()
		
		if not documents:
			item.set_sensitive(False)
		
		menu.append(item)
		
		item = Gtk.MenuItem(label=_("Clear Preview"))
		item.connect("activate", lambda x: self.updatePreview(self, True))
		menu.append(item)
		
		menu.show_all()
	
	def updatePreview(self, window, clear):
		view = self.window.get_active_view()
		
		if not view and not clear:
			return
		
		html = ""
		
		if not clear:
			doc = view.get_buffer()
			start = doc.get_start_iter()
			end = doc.get_end_iter()
			
			if doc.get_selection_bounds():
				start = doc.get_iter_at_mark(doc.get_insert())
				end = doc.get_iter_at_mark(doc.get_selection_bound())
			
			text = doc.get_text(start, end, True)
			
			if markdownVersion == "standard":
				html = htmlTemplate % (markdown.markdown(text, smart_emphasis=False), )
			else:
				html = htmlTemplate % (markdown.markdown(text, extensions=["extra",
				       "headerid(forceid=False)"]), )
		
		placement = self.scrolledWindow.get_placement()
		
		htmlDoc = self.htmlView
		htmlDoc.load_string(html, "text/html", "utf-8", "file:///")
		
		self.scrolledWindow.set_placement(placement)
	
	def urlTooltipVisible(self):
		if hasattr(self, "urlTooltip") and self.urlTooltip.get_property("visible"):
			return True
		
		return False
