// +------------------------------------------------------------------+
// |             ____ _               _        __  __ _  __           |
// |            / ___| |__   ___  ___| | __   |  \/  | |/ /           |
// |           | |   | '_ \ / _ \/ __| |/ /   | |\/| | ' /            |
// |           | |___| | | |  __/ (__|   <    | |  | | . \            |
// |            \____|_| |_|\___|\___|_|\_\___|_|  |_|_|\_\           |
// |                                                                  |
// | Copyright Mathias Kettner 2014             mk@mathias-kettner.de |
// +------------------------------------------------------------------+
//
// This file is part of Check_MK.
// The official homepage is at http://mathias-kettner.de/check_mk.
//
// check_mk is free software;  you can redistribute it and/or modify it
// under the  terms of the  GNU General Public License  as published by
// the Free Software Foundation in version 2.  check_mk is  distributed
// in the hope that it will be useful, but WITHOUT ANY WARRANTY;  with-
// out even the implied warranty of  MERCHANTABILITY  or  FITNESS FOR A
// PARTICULAR PURPOSE. See the  GNU General Public License for more de-
// ails.  You should have  received  a copy of the  GNU  General Public
// License along with GNU Make; see the file  COPYING.  If  not,  write
// to the Free Software Foundation, Inc., 51 Franklin St,  Fifth Floor,
// Boston, MA 02110-1301 USA.

import $ from "jquery";
import * as forms from "forms";
import * as ajax from "ajax";
import * as prediction from "prediction";

require("script-loader!./checkmk.js");
require("script-loader!./dashboard.js");
require("colorpicker");
require("script-loader!./wato.js");

// TODO: Find a better solution for this CEE specific include
try {
    require("script-loader!../../../enterprise/web/htdocs/js/graphs.js");
} catch(e) {} // eslint-disable-line no-empty

$(() => {
    forms.enable_select2();
});

export default {
    get_url: ajax.get_url,
    post_url: ajax.post_url,
    call_ajax: ajax.call_ajax,
    cmk: {
        prediction: prediction,
        ajax: ajax,
    }
};
