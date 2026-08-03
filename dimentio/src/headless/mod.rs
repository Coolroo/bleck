//! Rendering without a screen: `dimentio shot` and `dimentio reel`.
//!
//! Both write one contact sheet — or one looping GIF — through the same
//! software rasteriser the viewport draws with, so a caller with no display can
//! look at what it built. `shot` is one instant of a model from several angles;
//! `reel` is one effect at several instants of its own timeline. The split is
//! not cosmetic: what there is to check about a model is its shape from every
//! side, and what there is to check about an effect is when its parts run.
//!
//! The two commands share three things, and each is a module here rather than a
//! reach across from one command into the other:
//!
//! | module | what it owns |
//! |---|---|
//! | `args` | reading a number or a background name off the command line |
//! | `sheet` | the grid, the blit, and what a rendered cell measures |
//! | `encode` | writing the result out as a PNG or a looping GIF |
//!
//! ⚠️ **The dependency runs one way**: `shot` and `reel` read from the three
//! below them and neither reads from the other. `reel` used to import a dozen
//! names out of `shot`, which meant a change to the model command could not be
//! made without reading the effect command.

pub mod reel;
pub mod shot;

mod args;
mod encode;
mod sheet;
