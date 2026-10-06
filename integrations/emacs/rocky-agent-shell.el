;;; rocky-agent-shell.el --- Run agent-shell agents inside Rocky -*- lexical-binding: t; -*-

;; Copyright (C) 2026 Wesley Chow <wes.chow@gmail.com>
;; SPDX-License-Identifier: GPL-3.0-or-later

;;; Commentary:

;; Runs every agent-shell agent as `rocky run <agent command>', in a Rocky
;; container over the project directory.
;;
;; Needs agent-shell, from MELPA.
;;
;; Load with:
;;   (load "/path/to/rocky-sandbox/integrations/emacs/rocky-agent-shell.el")
;;
;; Then, from a buffer in the project:
;;   M-x agent-shell-pi-start-agent
;;   M-x agent-shell-anthropic-start-claude-code
;;
;; One-time setup on the host:
;;   rocky build
;;   rocky run --login claude
;;   rocky run pi          ; log in to pi

;;; Code:

(require 'agent-shell)

(defgroup rocky-agent-shell nil
  "Run agent-shell agents inside Rocky."
  :group 'agent-shell)

(defcustom rocky-agent-shell-program
  (or (executable-find "rocky")
      (expand-file-name "~/.local/bin/rocky"))
  "The rocky command on the host.
Editors started from a desktop launcher often lack the shell's PATH,
so the default is resolved once, at load time."
  :type 'file)

(defvar rocky-agent-shell--workspaces (make-hash-table :test #'equal)
  "Host directory -> where `rocky run' mounts it, from `rocky info workspace'.")

(defun rocky-agent-shell-workspace (host)
  "The directory where `rocky run' mounts HOST, ending in a slash.
Rocky names the mount after HOST and a hash of its real path, so
only Rocky can compute it."
  (or (gethash host rocky-agent-shell--workspaces)
      (puthash host
               (let ((default-directory host))
                 (file-name-as-directory
                  (car (process-lines rocky-agent-shell-program
                                      "info" "workspace"))))
               rocky-agent-shell--workspaces)))

(defun rocky-agent-shell-resolve-path (path)
  "Map PATH between the host project and its Rocky workspace, either way."
  (let* ((host (file-name-as-directory (expand-file-name (agent-shell-cwd))))
         (container (rocky-agent-shell-workspace host)))
    (cond
     ;; The project directory itself, host -> container.
     ((string= (file-name-as-directory path) host)
      (directory-file-name container))
     ;; A file in the project, host -> container.
     ((string-prefix-p host path)
      (concat container (substring path (length host))))
     ;; The workspace directory itself, container -> host.
     ((string= (file-name-as-directory path) container)
      (directory-file-name host))
     ;; A file in the workspace, container -> host.
     ((string-prefix-p container path)
      (let ((local (expand-file-name (substring path (length container)) host)))
        (if (file-in-directory-p local host)
            local
          (error "Resolves outside the project: %s" path))))
     (t
      (error "Path outside the Rocky workspace: %s" path)))))

;; agent-shell starts each agent in `agent-shell-cwd', so `rocky run'
;; mounts that directory.  The agent sees only container paths, and
;; agent-shell reads and writes the files it names on the host, so every
;; path between them goes through the resolver.
(setq agent-shell-command-prefix (list rocky-agent-shell-program "run"))
(setq agent-shell-path-resolver-function #'rocky-agent-shell-resolve-path)

;; Both adapters are installed in the Rocky image, so these names are
;; looked up inside the container.  (They are also the defaults.)
(setq agent-shell-pi-acp-command '("pi-acp"))
(setq agent-shell-anthropic-claude-acp-command '("claude-agent-acp"))

;; Use the login stored in Rocky's persistent home.  Environment variables
;; set in Emacs (API keys included) are not passed into the container.
(setq agent-shell-anthropic-authentication
      (agent-shell-anthropic-make-authentication :login t))

(provide 'rocky-agent-shell)
;;; rocky-agent-shell.el ends here
