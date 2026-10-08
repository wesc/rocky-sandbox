;;; rocky-agent-shell.el --- Run agent-shell agents inside Rocky -*- lexical-binding: t; -*-

;; Copyright (C) 2026 Wesley Chow <wes.chow@gmail.com>
;; SPDX-License-Identifier: GPL-3.0-or-later

;;; Commentary:

;; Runs agent-shell's agents with `rocky run'.  Needs agent-shell from MELPA.
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
  "The rocky command.
An Emacs started from a desktop launcher may lack the shell's PATH."
  :type 'file)

(defvar rocky-agent-shell--workspaces (make-hash-table :test #'equal)
  "Host directory -> output of `rocky info workspace' run there.")

(defun rocky-agent-shell-workspace (host)
  "Where `rocky run' mounts HOST, with a trailing slash.
The name hashes HOST's real path.  Ask Rocky; do not compute it."
  (or (gethash host rocky-agent-shell--workspaces)
      (puthash host
               (let ((default-directory host))
                 (file-name-as-directory
                  (car (process-lines rocky-agent-shell-program
                                      "info" "workspace"))))
               rocky-agent-shell--workspaces)))

(defun rocky-agent-shell-resolve-path (path)
  "Map PATH from host to container, or back."
  (let* ((host (file-name-as-directory (expand-file-name (agent-shell-cwd))))
         (container (rocky-agent-shell-workspace host)))
    (cond
     ;; Host project -> workspace.
     ((string= (file-name-as-directory path) host)
      (directory-file-name container))
     ;; Host file -> container file.
     ((string-prefix-p host path)
      (concat container (substring path (length host))))
     ;; Workspace -> host project.
     ((string= (file-name-as-directory path) container)
      (directory-file-name host))
     ;; Container file -> host file.
     ((string-prefix-p container path)
      (let ((local (expand-file-name (substring path (length container)) host)))
        (if (file-in-directory-p local host)
            local
          (error "Resolves outside the project: %s" path))))
     (t
      (error "Path outside the Rocky workspace: %s" path)))))

;; `rocky run' mounts `agent-shell-cwd'.  The agent sees container paths
;; and agent-shell does its file I/O on the host, so the resolver maps
;; every path between them.
(setq agent-shell-command-prefix (list rocky-agent-shell-program "run"))
(setq agent-shell-path-resolver-function #'rocky-agent-shell-resolve-path)

;; agent-shell's defaults.  The Rocky image installs both.
(setq agent-shell-pi-acp-command '("pi-acp"))
(setq agent-shell-anthropic-claude-acp-command '("claude-agent-acp"))

;; Log in from the profile home.  Emacs's environment, API keys included,
;; does not reach the container.
(setq agent-shell-anthropic-authentication
      (agent-shell-anthropic-make-authentication :login t))

(provide 'rocky-agent-shell)
;;; rocky-agent-shell.el ends here
